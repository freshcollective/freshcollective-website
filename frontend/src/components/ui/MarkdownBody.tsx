import React from 'react'

/**
 * Universal renderer for About page content.
 *
 * Detects format automatically:
 * - HTML (TipTap output starting with '<'): rendered via safe HTML parser
 * - Otherwise: treated as markdown (## h2, **bold**, * bullets, [text](url))
 *
 * No dangerouslySetInnerHTML. Only a fixed safe subset of tags is rendered.
 */

// ─────────────────────────────────────────────────────────────────────────────
// HTML mode
// ─────────────────────────────────────────────────────────────────────────────

function decodeEntities(html: string): string {
  return html
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
}

/** Only allow https?:// hrefs to prevent javascript: injection. */
function safeHref(raw: string): string | null {
  const h = raw.trim()
  return /^https?:\/\//i.test(h) ? h : null
}

/**
 * Parse a fragment of inline HTML (strong, em, a, text nodes).
 * Unknown tags are silently consumed (content preserved, tag stripped).
 */
function parseInlineHtml(html: string, keyBase: string): React.ReactNode {
  const nodes: React.ReactNode[] = []
  // Matches: <strong>…</strong> | <em>…</em> | <a href="…">…</a> | any other tag | text
  const re =
    /<strong[^>]*>([\s\S]*?)<\/strong>|<em[^>]*>([\s\S]*?)<\/em>|<a[^>]+href="([^"]*)"[^>]*>([\s\S]*?)<\/a>|<[^>]+>|([^<]+)/g
  let m: RegExpExecArray | null
  let idx = 0

  while ((m = re.exec(html)) !== null) {
    const k = `${keyBase}-${idx++}`
    if (m[1] !== undefined) {
      nodes.push(
        <strong key={k} className="font-semibold text-navy-900">
          {decodeEntities(m[1])}
        </strong>,
      )
    } else if (m[2] !== undefined) {
      nodes.push(<em key={k}>{decodeEntities(m[2])}</em>)
    } else if (m[3] !== undefined) {
      const href = safeHref(m[3])
      if (href) {
        nodes.push(
          <a
            key={k}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-teal-600 underline underline-offset-2 hover:text-teal-700"
          >
            {decodeEntities(m[4])}
          </a>,
        )
      } else {
        nodes.push(<React.Fragment key={k}>{decodeEntities(m[4])}</React.Fragment>)
      }
    } else if (m[5] !== undefined) {
      nodes.push(<React.Fragment key={k}>{decodeEntities(m[5])}</React.Fragment>)
    }
    // else: unknown/stripped tag — skip
  }

  return nodes
}

/**
 * Split TipTap HTML into top-level block tokens.
 * Handles nested content (e.g. <ul> containing <li><p>…</p></li>).
 */
type HtmlBlock =
  | { tag: 'h2' | 'h3' | 'p'; inner: string }
  | { tag: 'ul'; items: string[] }

function splitHtmlBlocks(html: string): HtmlBlock[] {
  const blocks: HtmlBlock[] = []
  const BLOCK = ['h2', 'h3', 'p', 'ul', 'ol']
  let i = 0

  while (i < html.length) {
    if (html[i] !== '<') { i++; continue }

    // Try to match an opening block tag
    const tagMatch = html.slice(i).match(/^<([a-z][a-z0-9]*)[^>]*>/)
    if (!tagMatch || !BLOCK.includes(tagMatch[1])) { i++; continue }

    const tag = tagMatch[1]
    const openLen = tagMatch[0].length
    const closeTag = `</${tag}>`

    // Walk forward to find the matching close tag (handles nesting)
    let depth = 1
    let j = i + openLen
    while (j < html.length && depth > 0) {
      if (html.slice(j, j + 1 + tag.length + 1).toLowerCase() === `<${tag}`) {
        depth++
        j++
      } else if (html.slice(j, j + closeTag.length).toLowerCase() === closeTag) {
        depth--
        if (depth === 0) break
        j += closeTag.length
      } else {
        j++
      }
    }

    const inner = html.slice(i + openLen, j)
    i = j + closeTag.length

    if (tag === 'ul' || tag === 'ol') {
      // Extract <li> contents, stripping inner <p> wrappers
      const liRe = /<li[^>]*>([\s\S]*?)<\/li>/g
      const items: string[] = []
      let liM: RegExpExecArray | null
      while ((liM = liRe.exec(inner)) !== null) {
        const liInner = liM[1]
        // Strip leading/trailing <p> wrapper that TipTap adds
        const pMatch = /<p[^>]*>([\s\S]*?)<\/p>/.exec(liInner)
        items.push(pMatch ? pMatch[1] : liInner)
      }
      if (items.length > 0) blocks.push({ tag: 'ul', items })
    } else if (tag === 'h2') {
      blocks.push({ tag: 'h2', inner })
    } else if (tag === 'h3') {
      blocks.push({ tag: 'h3', inner })
    } else if (tag === 'p' && inner.trim()) {
      blocks.push({ tag: 'p', inner })
    }
  }

  return blocks
}

function renderHtml(html: string): React.ReactNode {
  const blocks = splitHtmlBlocks(html)
  return blocks.map((b, i) => {
    const k = `hb-${i}`
    if (b.tag === 'h2') {
      return (
        <h2 key={k} className="mb-3 mt-7 text-[17px] font-bold text-navy-900 first:mt-0">
          {parseInlineHtml(b.inner, k)}
        </h2>
      )
    }
    if (b.tag === 'h3') {
      return (
        <h3 key={k} className="mb-2 mt-5 text-[15px] font-semibold text-navy-800">
          {parseInlineHtml(b.inner, k)}
        </h3>
      )
    }
    if (b.tag === 'ul') {
      return (
        <ul key={k} className="mb-4 space-y-1.5 pl-1">
          {b.items.map((item, idx) => (
            <li key={idx} className="flex items-start gap-2 text-[15px] leading-[1.75] text-slate-600">
              <span className="mt-[0.35em] h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />
              <span>{parseInlineHtml(item, `${k}-li${idx}`)}</span>
            </li>
          ))}
        </ul>
      )
    }
    // p
    return (
      <p key={k} className="mb-4 text-[15px] leading-[1.85] text-slate-600">
        {parseInlineHtml(b.inner, k)}
      </p>
    )
  })
}

// ─────────────────────────────────────────────────────────────────────────────
// Markdown mode (legacy / seed content)
// ─────────────────────────────────────────────────────────────────────────────

type MdToken =
  | { type: 'h2'; text: string }
  | { type: 'h3'; text: string }
  | { type: 'bullet'; items: MdInline[][] }
  | { type: 'paragraph'; segments: MdInline[] }
  | { type: 'blank' }

type MdInline =
  | { kind: 'text'; value: string }
  | { kind: 'bold'; value: string }
  | { kind: 'link'; text: string; href: string }

function parseMdInline(text: string): MdInline[] {
  const segs: MdInline[] = []
  const re = /\*\*(.+?)\*\*|\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) segs.push({ kind: 'text', value: text.slice(last, m.index) })
    if (m[0].startsWith('**')) {
      segs.push({ kind: 'bold', value: m[1] })
    } else {
      const href = m[3].trim()
      if (/^https?:\/\//i.test(href)) {
        segs.push({ kind: 'link', text: m[2], href })
      } else {
        segs.push({ kind: 'text', value: m[2] })
      }
    }
    last = m.index + m[0].length
  }
  if (last < text.length) segs.push({ kind: 'text', value: text.slice(last) })
  return segs
}

function renderMdInline(segs: MdInline[], keyBase: string): React.ReactNode {
  return segs.map((s, i) => {
    const k = `${keyBase}-${i}`
    if (s.kind === 'bold') {
      return <strong key={k} className="font-semibold text-navy-900">{s.value}</strong>
    }
    if (s.kind === 'link') {
      return (
        <a key={k} href={s.href} target="_blank" rel="noopener noreferrer"
           className="text-teal-600 underline underline-offset-2 hover:text-teal-700">
          {s.text}
        </a>
      )
    }
    return <React.Fragment key={k}>{s.value}</React.Fragment>
  })
}

function tokeniseMd(md: string): MdToken[] {
  const lines = md.split('\n')
  const tokens: MdToken[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i].trimEnd()

    if (line.startsWith('## ')) {
      tokens.push({ type: 'h2', text: line.slice(3) })
      i++
    } else if (line.startsWith('### ')) {
      tokens.push({ type: 'h3', text: line.slice(4) })
      i++
    } else if (line.startsWith('* ') || line.startsWith('- ')) {
      const items: MdInline[][] = []
      while (i < lines.length && (lines[i].startsWith('* ') || lines[i].startsWith('- '))) {
        items.push(parseMdInline(lines[i].slice(2)))
        i++
      }
      tokens.push({ type: 'bullet', items })
    } else if (line.trim() === '') {
      tokens.push({ type: 'blank' })
      i++
    } else {
      const paraLines: string[] = []
      while (
        i < lines.length &&
        lines[i].trim() !== '' &&
        !lines[i].startsWith('## ') &&
        !lines[i].startsWith('### ') &&
        !lines[i].startsWith('* ') &&
        !lines[i].startsWith('- ')
      ) {
        paraLines.push(lines[i].trimEnd())
        i++
      }
      tokens.push({ type: 'paragraph', segments: parseMdInline(paraLines.join('\n')) })
    }
  }
  return tokens
}

function renderMarkdown(md: string): React.ReactNode {
  const tokens = tokeniseMd(md)
  const nodes: React.ReactNode[] = []
  let key = 0

  for (const token of tokens) {
    if (token.type === 'blank') { key++; continue }

    if (token.type === 'h2') {
      nodes.push(
        <h2 key={key++} className="mb-3 mt-7 text-[17px] font-bold text-navy-900 first:mt-0">
          {token.text}
        </h2>,
      )
    } else if (token.type === 'h3') {
      nodes.push(
        <h3 key={key++} className="mb-2 mt-5 text-[15px] font-semibold text-navy-800">
          {token.text}
        </h3>,
      )
    } else if (token.type === 'bullet') {
      nodes.push(
        <ul key={key++} className="mb-4 space-y-1.5 pl-1">
          {token.items.map((item, idx) => (
            <li key={idx} className="flex items-start gap-2 text-[15px] leading-[1.75] text-slate-600">
              <span className="mt-[0.35em] h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />
              <span>{renderMdInline(item, `li${key}-${idx}`)}</span>
            </li>
          ))}
        </ul>,
      )
    } else if (token.type === 'paragraph') {
      nodes.push(
        <p key={key++} className="mb-4 text-[15px] leading-[1.85] text-slate-600" style={{ whiteSpace: 'pre-wrap' }}>
          {renderMdInline(token.segments, `p${key}`)}
        </p>,
      )
    }
  }

  return nodes
}

// ─────────────────────────────────────────────────────────────────────────────
// Public component
// ─────────────────────────────────────────────────────────────────────────────

interface Props {
  content: string
  className?: string
}

export default function MarkdownBody({ content, className = '' }: Props) {
  const trimmed = content.trim()
  const isHtml = /^<[a-z]/i.test(trimmed)
  return (
    <div className={className}>
      {isHtml ? renderHtml(trimmed) : renderMarkdown(trimmed)}
    </div>
  )
}
