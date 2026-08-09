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

    case 'paragraph': {
      const align = node.attrs?.textAlign as string | undefined
      const style: React.CSSProperties | undefined = align && align !== 'left' ? { textAlign: align as React.CSSProperties['textAlign'] } : undefined
      return (
        <p key={key} style={style} className="my-3 text-[15px] leading-[1.85] text-black first:mt-0 last:mb-0">
          {node.content?.length
            ? renderInlineContent(node.content, key)
            : <br />}
        </p>
      )
    }

    case 'heading': {
      const level = (node.attrs?.level as number) ?? 2
      // H1 is intentionally larger than H2; H2/H3 keep their pre-existing sizes
      // so previously-written Content blocks render byte-identically. Heading
      // colour comes from inline `textStyle` marks (set via the editor's
      // colour swatches) and overrides the Tailwind text-navy-900 default.
      const className = level === 1
        ? 'mt-7 mb-3 font-semibold text-[1.45rem] leading-snug text-navy-900 first:mt-0'
        : level === 2
        ? 'mt-6 mb-2 font-semibold text-[1.15rem] leading-snug text-navy-900 first:mt-0'
        : 'mt-5 mb-2 font-semibold text-[1.0rem] leading-snug text-navy-900 first:mt-0'
      const align = node.attrs?.textAlign as string | undefined
      const style: React.CSSProperties | undefined = align && align !== 'left' ? { textAlign: align as React.CSSProperties['textAlign'] } : undefined
      return React.createElement(
        `h${level}`,
        { key, className, style },
        renderInlineContent(node.content, key),
      )
    }

    // Lists — scope every list-marker rule inside `rich-text-content`
    // so nested lists get the correct marker (disc → circle → square,
    // decimal → lower-alpha → lower-roman) without changing global
    // Tailwind preflight. The keyed styles below live inside the
    // component's inline <style>, applied through the outer wrapper.
    case 'bulletList':
      return (
        <ul key={key} className="rt-ul my-3 pl-6 text-[15px] leading-[1.8] text-black">
          {node.content?.map((child, i) => renderNode(child, `${key}-${i}`))}
        </ul>
      )

    case 'orderedList':
      return (
        <ol key={key} className="rt-ol my-3 pl-6 text-[15px] leading-[1.8] text-black">
          {node.content?.map((child, i) => renderNode(child, `${key}-${i}`))}
        </ol>
      )

    case 'listItem':
      return (
        <li key={key} className="rt-li my-1">
          {node.content?.map((child, i) => renderNode(child, `${key}-${i}`))}
        </li>
      )

    case 'blockquote':
      // Blockquote accent reads a scoped CSS variable so that a quote
      // inside a palette-coloured container adopts the container's own
      // accent instead of the platform default teal. The variable is
      // set by ``withContainerBase`` (member) and ``BlockPreview``
      // (editor); when no container is active the fallback keeps the
      // long-standing teal-300 look.
      return (
        <blockquote
          key={key}
          className="my-4 border-l-4 pl-4 italic text-black"
          style={{ borderColor: 'var(--fc-quote-accent, #5eead4)' }}
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

    case 'table':
      return (
        <div key={key} className="rt-table-wrap my-4 overflow-x-auto">
          <table className="rt-table">
            <tbody>
              {node.content?.map((row, i) => renderNode(row, `${key}-${i}`))}
            </tbody>
          </table>
        </div>
      )

    case 'tableRow':
      return (
        <tr key={key}>
          {node.content?.map((cell, i) => renderNode(cell, `${key}-${i}`))}
        </tr>
      )

    case 'tableHeader':
      return (
        <th
          key={key}
          colSpan={(node.attrs?.colspan as number | undefined) ?? undefined}
          rowSpan={(node.attrs?.rowspan as number | undefined) ?? undefined}
        >
          {node.content?.map((child, i) => renderNode(child, `${key}-${i}`))}
        </th>
      )

    case 'tableCell':
      return (
        <td
          key={key}
          colSpan={(node.attrs?.colspan as number | undefined) ?? undefined}
          rowSpan={(node.attrs?.rowspan as number | undefined) ?? undefined}
        >
          {node.content?.map((child, i) => renderNode(child, `${key}-${i}`))}
        </td>
      )

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

/**
 * Scoped list styling — restores markers stripped by Tailwind preflight.
 *
 * We keep the styles inside a single ``.rich-text-content`` wrapper so
 * global `<ul>` behaviour elsewhere in the app stays untouched. Every
 * surface that displays authored rich text (Creator Studio preview,
 * pathway step page, About page, member-facing views) renders through
 * this component, so a single fix here reaches every consumer.
 */
const RICH_TEXT_STYLES = `
.rich-text-content ul.rt-ul {
  list-style: disc outside;
  padding-inline-start: 1.5rem;
}
.rich-text-content ol.rt-ol {
  list-style: decimal outside;
  padding-inline-start: 1.75rem;
}
.rich-text-content ul.rt-ul ul.rt-ul { list-style-type: circle; }
.rich-text-content ul.rt-ul ul.rt-ul ul.rt-ul { list-style-type: square; }
.rich-text-content ol.rt-ol ol.rt-ol { list-style-type: lower-alpha; }
.rich-text-content ol.rt-ol ol.rt-ol ol.rt-ol { list-style-type: lower-roman; }
.rich-text-content li.rt-li { padding-inline-start: 0.25rem; }
.rich-text-content li.rt-li::marker {
  color: rgba(15, 23, 42, 0.55);
}
.rich-text-content li.rt-li > p:only-child { margin: 0; }
.rich-text-content li.rt-li > p { margin-top: 0.25rem; margin-bottom: 0.25rem; }

/* Tables — scoped so the rest of the app's tables (if any) stay untouched.
   .rt-table-wrap gives us horizontal overflow on small screens without
   breaking layout; the table itself gets clear cell borders and a
   distinct header row. */
.rich-text-content .rt-table-wrap {
  border: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 8px;
  -webkit-overflow-scrolling: touch;
}
.rich-text-content table.rt-table {
  border-collapse: collapse;
  min-width: 100%;
  font-size: 14.5px;
  line-height: 1.6;
}
.rich-text-content table.rt-table th,
.rich-text-content table.rt-table td {
  border: 1px solid rgba(15, 23, 42, 0.12);
  padding: 8px 12px;
  vertical-align: top;
  text-align: left;
}
.rich-text-content table.rt-table th {
  background: rgba(56, 160, 158, 0.08);
  color: #0f172a;
  font-weight: 600;
}
.rich-text-content table.rt-table tr:nth-child(even) td {
  background: rgba(15, 23, 42, 0.02);
}
.rich-text-content table.rt-table p { margin: 0; }
`


export default function RichTextRenderer({ content, className }: Props) {
  if (!content) return null

  const wrapperClass = `rich-text-content ${className ?? ''}`

  // Try to parse as TipTap JSON
  try {
    const parsed = JSON.parse(content) as DocNode
    if (parsed?.type === 'doc') {
      return (
        <>
          <style>{RICH_TEXT_STYLES}</style>
          <div className={wrapperClass}>
            {renderNode(parsed, 'root')}
          </div>
        </>
      )
    }
  } catch {}

  // Fallback: render as legacy plain text with basic paragraph splitting
  return (
    <>
      <style>{RICH_TEXT_STYLES}</style>
      <div className={wrapperClass}>
        {content.split('\n\n').filter(Boolean).map((para, i) => {
          if (para === '---') return <hr key={i} className="my-6 border-slate-200" />
          return (
            <p key={i} className="my-3 text-[15px] leading-[1.85] text-black">
              {para}
            </p>
          )
        })}
      </div>
    </>
  )
}
