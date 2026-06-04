import React from 'react'

/**
 * Safe, minimal markdown renderer for creator-authored content.
 * Supports: ## h2, ### h3, **bold**, [text](url) links, * bullet lists, paragraphs.
 * No external dependencies, no dangerouslySetInnerHTML.
 */

type Token =
  | { type: 'h2'; text: string }
  | { type: 'h3'; text: string }
  | { type: 'bullet'; items: InlineSegment[][] }
  | { type: 'paragraph'; segments: InlineSegment[] }
  | { type: 'blank' }

type InlineSegment =
  | { kind: 'text'; value: string }
  | { kind: 'bold'; value: string }
  | { kind: 'link'; text: string; href: string }

// Only allow http/https URLs — reject javascript: and data: schemes
function safeHref(raw: string): string | null {
  const trimmed = raw.trim()
  if (/^https?:\/\//i.test(trimmed)) return trimmed
  return null
}

function parseInline(text: string): InlineSegment[] {
  const segments: InlineSegment[] = []
  // Match **bold** and [text](url) interleaved
  const re = /\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\)/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) segments.push({ kind: 'text', value: text.slice(last, m.index) })
    if (m[0].startsWith('**')) {
      segments.push({ kind: 'bold', value: m[1] })
    } else {
      const href = safeHref(m[3])
      if (href) {
        segments.push({ kind: 'link', text: m[2], href })
      } else {
        // Unsafe URL — render as plain text
        segments.push({ kind: 'text', value: m[2] })
      }
    }
    last = m.index + m[0].length
  }
  if (last < text.length) segments.push({ kind: 'text', value: text.slice(last) })
  return segments
}

function renderInline(segments: InlineSegment[], key: string): React.ReactNode {
  return segments.map((s, i) => {
    if (s.kind === 'bold') {
      return <strong key={`${key}-b${i}`} className="font-semibold text-navy-900">{s.value}</strong>
    }
    if (s.kind === 'link') {
      return (
        <a
          key={`${key}-a${i}`}
          href={s.href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-teal-600 underline underline-offset-2 hover:text-teal-700"
        >
          {s.text}
        </a>
      )
    }
    return <React.Fragment key={`${key}-t${i}`}>{s.value}</React.Fragment>
  })
}

function tokenise(md: string): Token[] {
  const lines = md.split('\n')
  const tokens: Token[] = []
  let i = 0

  while (i < lines.length) {
    const raw = lines[i]
    const line = raw.trimEnd()

    if (line.startsWith('## ')) {
      tokens.push({ type: 'h2', text: line.slice(3) })
      i++
    } else if (line.startsWith('### ')) {
      tokens.push({ type: 'h3', text: line.slice(4) })
      i++
    } else if (line.startsWith('* ') || line.startsWith('- ')) {
      const items: InlineSegment[][] = []
      while (i < lines.length && (lines[i].startsWith('* ') || lines[i].startsWith('- '))) {
        items.push(parseInline(lines[i].slice(2)))
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
      tokens.push({ type: 'paragraph', segments: parseInline(paraLines.join('\n')) })
    }
  }
  return tokens
}

interface Props {
  content: string
  className?: string
}

export default function MarkdownBody({ content, className = '' }: Props) {
  const tokens = tokenise(content)

  const nodes: React.ReactNode[] = []
  let key = 0

  for (const token of tokens) {
    if (token.type === 'blank') {
      key++
      continue
    }

    if (token.type === 'h2') {
      nodes.push(
        <h2
          key={key++}
          className="mb-3 mt-7 text-[17px] font-bold text-navy-900 first:mt-0"
        >
          {token.text}
        </h2>
      )
    } else if (token.type === 'h3') {
      nodes.push(
        <h3
          key={key++}
          className="mb-2 mt-5 text-[15px] font-semibold text-navy-800"
        >
          {token.text}
        </h3>
      )
    } else if (token.type === 'bullet') {
      nodes.push(
        <ul key={key++} className="mb-4 space-y-1.5 pl-1">
          {token.items.map((item, idx) => (
            <li key={idx} className="flex items-start gap-2 text-[15px] leading-[1.75] text-slate-600">
              <span className="mt-[0.35em] h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />
              <span>{renderInline(item, `li${key}-${idx}`)}</span>
            </li>
          ))}
        </ul>
      )
    } else if (token.type === 'paragraph') {
      nodes.push(
        <p
          key={key++}
          className="mb-4 text-[15px] leading-[1.85] text-slate-600"
          style={{ whiteSpace: 'pre-wrap' }}
        >
          {renderInline(token.segments, `p${key}`)}
        </p>
      )
    }
  }

  return <div className={className}>{nodes}</div>
}
