import React from 'react'

// ---------------------------------------------------------------------------
// TipTap JSON node types
// ---------------------------------------------------------------------------

interface TextMark {
  type: 'bold' | 'italic' | 'underline' | 'link' | 'code' | 'textStyle' | 'highlight' | string
  attrs?: {
    href?: string; target?: string; rel?: string
    color?: string; fontFamily?: string
  }
}

interface DocNode {
  type: string
  attrs?: Record<string, unknown>
  content?: DocNode[]
  text?: string
  marks?: TextMark[]
}

// ---------------------------------------------------------------------------
// Safety validation
// ---------------------------------------------------------------------------

// Accept #rgb and #rrggbb only — block rgb(), hsl(), url(), expressions, etc.
function isSafeHex(value: string | undefined): value is string {
  if (!value) return false
  return /^#[0-9A-Fa-f]{3}([0-9A-Fa-f]{3})?$/.test(value.trim())
}

// Explicit allowlist for font families — unknown values are silently ignored
const ALLOWED_FONTS: Record<string, string> = {
  'Georgia, serif':                                                    'Georgia, serif',
  'Times New Roman, serif':                                            'Times New Roman, serif',
  'Arial, sans-serif':                                                 'Arial, sans-serif',
  'Helvetica, Arial, sans-serif':                                      'Helvetica, Arial, sans-serif',
  'Trebuchet MS, sans-serif':                                          'Trebuchet MS, sans-serif',
  'monospace':                                                         'monospace',
  'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace':  'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function isRichTextJSON(content: string | null): boolean {
  if (!content) return false
  try {
    const parsed = JSON.parse(content)
    return parsed?.type === 'doc'
  } catch {
    return false
  }
}

function applyMarks(text: string, marks: TextMark[] | undefined, key: string): React.ReactNode {
  if (!marks || marks.length === 0) return text

  let node: React.ReactNode = text
  for (const mark of [...marks].reverse()) {
    if (mark.type === 'bold') {
      node = <strong key={`${key}-b`}>{node}</strong>
    } else if (mark.type === 'italic') {
      node = <em key={`${key}-i`}>{node}</em>
    } else if (mark.type === 'underline') {
      node = <u key={`${key}-u`}>{node}</u>
    } else if (mark.type === 'code') {
      node = <code key={`${key}-c`} className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em]">{node}</code>
    } else if (mark.type === 'link') {
      const href = mark.attrs?.href ?? '#'
      // Only allow http/https/mailto — strip javascript: and data: URIs
      const safeSrc = /^(https?:|mailto:)/.test(href) ? href : '#'
      node = (
        <a
          key={`${key}-a`}
          href={safeSrc}
          target="_blank"
          rel="noopener noreferrer"
          className="text-teal-700 underline underline-offset-2 hover:opacity-80"
        >
          {node}
        </a>
      )
    } else if (mark.type === 'textStyle') {
      const style: React.CSSProperties = {}
      const color = mark.attrs?.color
      if (isSafeHex(color)) style.color = color
      const font = mark.attrs?.fontFamily
      if (font && ALLOWED_FONTS[font]) style.fontFamily = ALLOWED_FONTS[font]
      if (Object.keys(style).length > 0) {
        node = <span key={`${key}-ts`} style={style}>{node}</span>
      }
    } else if (mark.type === 'highlight') {
      const color = mark.attrs?.color
      if (isSafeHex(color)) {
        node = <mark key={`${key}-hl`} style={{ backgroundColor: color, borderRadius: '2px', padding: '0 2px' }}>{node}</mark>
      }
    }
  }
  return node
}

function renderInlineContent(nodes: DocNode[] | undefined, keyBase: string): React.ReactNode[] {
  if (!nodes) return []
  return nodes.map((node, i) => {
    const key = `${keyBase}-${i}`
    if (node.type === 'text') {
      return <React.Fragment key={key}>{applyMarks(node.text ?? '', node.marks, key)}</React.Fragment>
    }
    if (node.type === 'hardBreak') {
      return <br key={key} />
    }
    return null
  })
}

function renderNode(node: DocNode, key: string): React.ReactNode {
  switch (node.type) {
    case 'doc':
      return (
        <React.Fragment key={key}>
          {node.content?.map((child, i) => renderNode(child, `${key}-${i}`))}
        </React.Fragment>
      )

    case 'paragraph':
      return (
        <p key={key} className="my-3 text-[15px] leading-[1.85] text-slate-700 first:mt-0 last:mb-0">
          {node.content?.length
            ? renderInlineContent(node.content, key)
            : <br />}
        </p>
      )

    case 'heading': {
      const level = (node.attrs?.level as number) ?? 2
      const className = level === 2
        ? 'mt-6 mb-2 font-semibold text-[1.15rem] leading-snug text-navy-900 first:mt-0'
        : 'mt-5 mb-2 font-semibold text-[1.0rem] leading-snug text-navy-900 first:mt-0'
      return React.createElement(
        `h${level}`,
        { key, className },
        renderInlineContent(node.content, key),
      )
    }

    case 'bulletList':
      return (
        <ul key={key} className="my-3 space-y-1 pl-5 text-[15px] leading-[1.8] text-slate-700">
          {node.content?.map((child, i) => renderNode(child, `${key}-${i}`))}
        </ul>
      )

    case 'orderedList':
      return (
        <ol key={key} className="my-3 list-decimal space-y-1 pl-5 text-[15px] leading-[1.8] text-slate-700">
          {node.content?.map((child, i) => renderNode(child, `${key}-${i}`))}
        </ol>
      )

    case 'listItem':
      return (
        <li key={key}>
          {node.content?.map((child, i) => renderNode(child, `${key}-${i}`))}
        </li>
      )

    case 'blockquote':
      return (
        <blockquote
          key={key}
          className="my-4 border-l-4 border-teal-300 pl-4 italic text-slate-600"
        >
          {node.content?.map((child, i) => renderNode(child, `${key}-${i}`))}
        </blockquote>
      )

    case 'codeBlock':
      return (
        <pre key={key} className="my-3 overflow-x-auto rounded-lg bg-slate-100 p-4 font-mono text-sm text-slate-800">
          {node.content?.map((child, i) => renderNode(child, `${key}-${i}`))}
        </pre>
      )

    case 'horizontalRule':
      return <hr key={key} className="my-6 border-slate-200" />

    case 'text':
      return (
        <React.Fragment key={key}>
          {applyMarks(node.text ?? '', node.marks, key)}
        </React.Fragment>
      )

    default:
      return null
  }
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

interface Props {
  content: string | null
  className?: string
}

export default function RichTextRenderer({ content, className }: Props) {
  if (!content) return null

  // Try to parse as TipTap JSON
  try {
    const parsed = JSON.parse(content) as DocNode
    if (parsed?.type === 'doc') {
      return (
        <div className={className}>
          {renderNode(parsed, 'root')}
        </div>
      )
    }
  } catch {}

  // Fallback: render as legacy plain text with basic paragraph splitting
  return (
    <div className={className}>
      {content.split('\n\n').filter(Boolean).map((para, i) => {
        if (para === '---') return <hr key={i} className="my-6 border-slate-200" />
        return (
          <p key={i} className="my-3 text-[15px] leading-[1.85] text-slate-700">
            {para}
          </p>
        )
      })}
    </div>
  )
}
