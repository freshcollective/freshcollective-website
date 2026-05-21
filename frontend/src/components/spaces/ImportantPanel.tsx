import React from 'react'

// ---------------------------------------------------------------------------
// Minimal safe rich-text renderer for the Important panel.
//
// Accepts TipTap JSON (stored by SimpleRichTextEditor) or plain text.
// All link hrefs are validated against http/https before rendering.
// No dangerouslySetInnerHTML is used.
// ---------------------------------------------------------------------------

interface TextMark {
  type: string
  attrs?: { href?: string; target?: string; rel?: string }
}

interface DocNode {
  type: string
  attrs?: Record<string, unknown>
  content?: DocNode[]
  text?: string
  marks?: TextMark[]
}

function safeHref(href: string | undefined): string {
  if (!href) return '#'
  return /^https?:\/\//.test(href) ? href : '#'
}

function renderInline(nodes: DocNode[] | undefined, base: string): React.ReactNode[] {
  if (!nodes) return []
  return nodes.map((node, i) => {
    const key = `${base}-${i}`
    if (node.type === 'hardBreak') return <br key={key} />
    if (node.type !== 'text') return null
    let el: React.ReactNode = node.text ?? ''
    for (const mark of [...(node.marks ?? [])].reverse()) {
      if (mark.type === 'bold')   el = <strong key={`${key}-b`}>{el}</strong>
      if (mark.type === 'italic') el = <em key={`${key}-i`}>{el}</em>
      if (mark.type === 'link') {
        el = (
          <a
            key={`${key}-a`}
            href={safeHref(mark.attrs?.href)}
            target="_blank"
            rel="noopener noreferrer"
            className="text-teal-700 underline underline-offset-2 hover:opacity-80"
          >
            {el}
          </a>
        )
      }
    }
    return <React.Fragment key={key}>{el}</React.Fragment>
  })
}

function renderDocNode(node: DocNode, key: string): React.ReactNode {
  switch (node.type) {
    case 'doc':
      return (
        <React.Fragment key={key}>
          {node.content?.map((c, i) => renderDocNode(c, `${key}-${i}`))}
        </React.Fragment>
      )
    case 'paragraph':
      if (!node.content?.length) return <br key={key} />
      return (
        <p key={key} className="mb-1.5 last:mb-0 text-[12px] leading-relaxed text-slate-500">
          {renderInline(node.content, key)}
        </p>
      )
    case 'bulletList':
      return (
        <ul key={key} className="mb-1.5 list-disc pl-4 text-[12px] leading-relaxed text-slate-500 space-y-0.5">
          {node.content?.map((c, i) => renderDocNode(c, `${key}-${i}`))}
        </ul>
      )
    case 'orderedList':
      return (
        <ol key={key} className="mb-1.5 list-decimal pl-4 text-[12px] leading-relaxed text-slate-500 space-y-0.5">
          {node.content?.map((c, i) => renderDocNode(c, `${key}-${i}`))}
        </ol>
      )
    case 'listItem':
      return (
        <li key={key}>
          {node.content?.map((c, i) => renderDocNode(c, `${key}-${i}`))}
        </li>
      )
    default:
      return null
  }
}

function PanelBody({ content }: { content: string | null | undefined }) {
  if (!content) return null

  // Try TipTap JSON first
  try {
    const parsed = JSON.parse(content) as DocNode
    if (parsed?.type === 'doc') {
      return <div>{renderDocNode(parsed, 'root')}</div>
    }
  } catch {}

  // Plain text fallback — preserves line breaks
  return (
    <p className="text-[12px] leading-relaxed text-slate-500 whitespace-pre-line">{content}</p>
  )
}

// ---------------------------------------------------------------------------
// Panel component
// ---------------------------------------------------------------------------

interface Props {
  startTitle?: string | null
  startBody?: string | null
  focusTitle?: string | null
  focusBody?: string | null
  linksTitle?: string | null
  linksBody?: string | null
}

const DEFAULTS = {
  startTitle: 'Start here',
  startBody:  null,
  focusTitle: 'Upcoming focus',
  focusBody:  null,
  linksTitle: 'Helpful links',
  linksBody:  null,
}

export default function ImportantPanel({
  startTitle,
  startBody,
  focusTitle,
  focusBody,
  linksTitle,
  linksBody,
}: Props) {
  const sections = [
    { title: startTitle || DEFAULTS.startTitle, body: startBody ?? DEFAULTS.startBody },
    { title: focusTitle || DEFAULTS.focusTitle, body: focusBody ?? DEFAULTS.focusBody },
    { title: linksTitle || DEFAULTS.linksTitle, body: linksBody ?? DEFAULTS.linksBody },
  ]

  return (
    <div
      className="rounded-2xl bg-white px-5 py-6"
      style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
    >
      <div
        className="mb-3 h-[2px] w-5 rounded-full"
        style={{ background: 'linear-gradient(90deg, #BF9830 0%, transparent 100%)' }}
      />
      <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
        Important
      </p>

      <div className="flex flex-col gap-4">
        {sections.map(({ title, body }, i) => (
          <React.Fragment key={title}>
            {i > 0 && <div className="h-px" style={{ background: 'rgba(0,0,0,0.06)' }} />}
            <div>
              <p className="mb-1.5 text-[13px] font-semibold text-navy-900">{title}</p>
              {body ? (
                <PanelBody content={body} />
              ) : (
                <p className="text-[12px] leading-relaxed text-slate-400 italic">
                  Nothing added yet.
                </p>
              )}
            </div>
          </React.Fragment>
        ))}
      </div>
    </div>
  )
}
