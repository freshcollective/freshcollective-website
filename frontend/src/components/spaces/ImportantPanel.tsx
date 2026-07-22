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
        <p key={key} className="mb-1.5 last:mb-0 text-[12px] leading-relaxed text-black">
          {renderInline(node.content, key)}
        </p>
      )
    case 'bulletList':
      return (
        <ul key={key} className="mb-1.5 list-disc pl-4 text-[12px] leading-relaxed text-black space-y-0.5">
          {node.content?.map((c, i) => renderDocNode(c, `${key}-${i}`))}
        </ul>
      )
    case 'orderedList':
      return (
        <ol key={key} className="mb-1.5 list-decimal pl-4 text-[12px] leading-relaxed text-black space-y-0.5">
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

function tryParseDoc(content: string): DocNode | null {
  try {
    const parsed = JSON.parse(content) as DocNode
    return parsed?.type === 'doc' ? parsed : null
  } catch {
    return null
  }
}

function PanelBody({ content }: { content: string | null | undefined }) {
  if (!content) return null

  const doc = tryParseDoc(content)
  if (doc) {
    return <div>{renderDocNode(doc, 'root')}</div>
  }

  // Plain text fallback — preserves line breaks
  return (
    <p className="text-[12px] leading-relaxed text-black whitespace-pre-line">{content}</p>
  )
}

// ---------------------------------------------------------------------------
// Panel component
// ---------------------------------------------------------------------------

/**
 * Member Hub panel sections. Labels are FIXED across all collectives —
 * "Welcome", "This week", "Notes". The old per-space `guidance_*_title`
 * fields remain in the DB for round-trip stability but are no longer
 * surfaced to members or editable by creators.
 */
interface Props {
  welcomeBody?: string | null
  notesBody?: string | null
  /**
   * When provided, replaces the middle "This week" section's body with
   * pre-rendered JSX. Used to inject the automatic upcoming-Gatherings
   * schedule.
   */
  focusOverride?: React.ReactNode
}

// ---------------------------------------------------------------------------
// ImportantPanelContent — sections only, no outer card wrapper.
// Use this when embedding inside a shared card (e.g. CollectiveSidebarPanel).
// ---------------------------------------------------------------------------

interface ContentProps extends Props {
  className?: string
}

export function ImportantPanelContent({
  welcomeBody,
  notesBody,
  focusOverride,
  className,
}: ContentProps) {
  const sections: Array<{ title: string; body: string | null | undefined; override?: React.ReactNode }> = [
    { title: 'Welcome',   body: welcomeBody },
    { title: 'This week', body: null, override: focusOverride },
    { title: 'Notes',     body: notesBody },
  ]

  return (
    <div className={className}>
      <div
        className="mb-3 h-[2px] w-5 rounded-full"
        style={{ background: 'linear-gradient(90deg, #BF9830 0%, transparent 100%)' }}
      />
      <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.16em] text-black">
        Important
      </p>

      <div className="flex flex-col gap-4">
        {sections.map(({ title, body, override }, i) => (
          <React.Fragment key={title}>
            {i > 0 && <div className="h-px" style={{ background: 'rgba(0,0,0,0.06)' }} />}
            <div>
              <p className="mb-1.5 text-[13px] font-semibold text-navy-900">{title}</p>
              {override !== undefined ? (
                override
              ) : body ? (
                <PanelBody content={body} />
              ) : (
                <p className="text-[12px] leading-relaxed text-black italic">
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

// ---------------------------------------------------------------------------
// ImportantPanel — standalone card with own border/shadow.
// Use this when the panel appears without a banner image above it.
// ---------------------------------------------------------------------------

export default function ImportantPanel({
  welcomeBody,
  notesBody,
  focusOverride,
}: Props) {
  return (
    <div
      className="rounded-2xl bg-white px-5 py-6"
      style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
    >
      <ImportantPanelContent
        welcomeBody={welcomeBody}
        notesBody={notesBody}
        focusOverride={focusOverride}
      />
    </div>
  )
}
