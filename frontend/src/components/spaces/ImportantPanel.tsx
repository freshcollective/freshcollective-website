import React from 'react'
import {
  docHasContent,
  docLeadsWithHeading,
  tryParseDoc,
  type RichTextMark,
  type RichTextNode,
} from '@/lib/richTextDoc'

// ---------------------------------------------------------------------------
// Minimal safe rich-text renderer for the Important panel.
//
// Accepts TipTap JSON (stored by SimpleRichTextEditor) or plain text.
// All link hrefs are validated against http/https before rendering.
// No dangerouslySetInnerHTML is used.
//
// Round-trip guarantee: every node type authored in Creator Studio
// must render in the Member Hub. This renderer walks the whole doc
// and never silently drops nodes — unknown block-level nodes fall
// through to render their inline content so text is never lost.
// ---------------------------------------------------------------------------


function safeHref(href: string | undefined): string {
  if (!href) return '#'
  return /^https?:\/\//.test(href) ? href : '#'
}

function renderInline(nodes: RichTextNode[] | undefined, base: string): React.ReactNode[] {
  if (!nodes) return []
  return nodes.map((node, i) => {
    const key = `${base}-${i}`
    if (node.type === 'hardBreak') return <br key={key} />
    if (node.type !== 'text') return null
    let el: React.ReactNode = node.text ?? ''
    for (const mark of [...(node.marks ?? [])].reverse()) {
      if (mark.type === 'bold')   el = <strong key={`${key}-b`}>{el}</strong>
      if (mark.type === 'italic') el = <em key={`${key}-i`}>{el}</em>
      if (mark.type === 'code')   el = (
        <code
          key={`${key}-c`}
          className="rounded bg-slate-100 px-1 py-0.5 text-[11.5px] font-mono text-navy-800"
        >{el}</code>
      )
      if (mark.type === 'link') {
        el = (
          <a
            key={`${key}-a`}
            href={safeHref(mark.attrs?.href)}
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2 hover:opacity-80"
            style={{ color: 'var(--fc-accent, #0f766e)' }}
          >
            {el}
          </a>
        )
      }
    }
    return <React.Fragment key={key}>{el}</React.Fragment>
  })
}

// Panel-scale heading sizes. Headings authored in Creator Studio
// must show up in the Member Hub — but the panel is a compact 12px
// scale, so headings step up modestly rather than dominate. Level
// beyond 3 collapses to the h4 style; TipTap allows 1–6 but
// Creators rarely reach for h5/h6 in a small panel.
const HEADING_CLASS: Record<number, string> = {
  1: 'mt-1 mb-2 font-serif text-[16px] font-semibold leading-snug text-navy-900',
  2: 'mt-3 mb-1.5 text-[14px] font-semibold leading-snug text-navy-900',
  3: 'mt-2.5 mb-1 text-[13px] font-semibold leading-snug text-navy-900',
  4: 'mt-2 mb-1 text-[12.5px] font-semibold leading-snug text-navy-800',
}

function headingClass(level: number): string {
  return HEADING_CLASS[level] ?? HEADING_CLASS[4]
}

function renderDocNode(node: RichTextNode, key: string): React.ReactNode {
  switch (node.type) {
    case 'doc':
      return (
        <React.Fragment key={key}>
          {node.content?.map((c, i) => renderDocNode(c, `${key}-${i}`))}
        </React.Fragment>
      )
    case 'heading': {
      const level = Math.max(1, Math.min(6, Number(node.attrs?.level ?? 2)))
      const cls = headingClass(level)
      // Render as an actual h1..h6 so screen readers and browser
      // outlines see the structure the Creator authored.
      const children = renderInline(node.content, key)
      switch (level) {
        case 1: return <h1 key={key} className={cls}>{children}</h1>
        case 2: return <h2 key={key} className={cls}>{children}</h2>
        case 3: return <h3 key={key} className={cls}>{children}</h3>
        case 4: return <h4 key={key} className={cls}>{children}</h4>
        case 5: return <h5 key={key} className={cls}>{children}</h5>
        default: return <h6 key={key} className={cls}>{children}</h6>
      }
    }
    case 'paragraph':
      // Empty paragraphs are visible spacing: render as a real <p>
      // with a non-breaking space so vertical rhythm is preserved
      // between prose blocks. Previously collapsed to <br>, which
      // has no line-height and swallowed the intended gap.
      if (!node.content?.length) {
        return (
          <p key={key} className="mb-3 h-3 last:mb-0" aria-hidden="true">
            {'\u00A0'}
          </p>
        )
      }
      return (
        <p key={key} className="mb-3 last:mb-0 text-[12.5px] leading-relaxed text-black">
          {renderInline(node.content, key)}
        </p>
      )
    case 'bulletList':
      return (
        <ul key={key} className="mb-3 list-disc pl-4 text-[12.5px] leading-relaxed text-black space-y-1">
          {node.content?.map((c, i) => renderDocNode(c, `${key}-${i}`))}
        </ul>
      )
    case 'orderedList':
      return (
        <ol key={key} className="mb-3 list-decimal pl-4 text-[12.5px] leading-relaxed text-black space-y-1">
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
      // Unknown block — walk its inline children so text isn't
      // silently dropped. Better a rendered paragraph than a missing
      // sentence.
      if (!node.content?.length) return null
      return (
        <p key={key} className="mb-3 last:mb-0 text-[12.5px] leading-relaxed text-black">
          {renderInline(node.content, key)}
        </p>
      )
  }
}

function PanelBody({ content }: { content: string | null | undefined }) {
  if (!content) return null

  const doc = tryParseDoc(content)
  if (doc) {
    return <div>{renderDocNode(doc, 'root')}</div>
  }

  // Plain text fallback — preserves line breaks for older rows saved
  // before the TipTap editor shipped.
  return (
    <p className="text-[12.5px] leading-relaxed text-black whitespace-pre-line">{content}</p>
  )
}

// ---------------------------------------------------------------------------
// Panel component
// ---------------------------------------------------------------------------

/**
 * Member Hub panel sections. The fixed labels ("Welcome" / "Notes")
 * remain as an orientation eyebrow when the Creator's body is empty
 * OR when they didn't author their own leading heading. When the
 * Creator's body opens with a heading, that heading IS the section
 * title and the fixed eyebrow is suppressed to avoid two stacked
 * titles above the same body.
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

interface SectionConfig {
  title: string
  body: string | null | undefined
  override?: React.ReactNode
  /** True when this section's body is Creator-authored (i.e. the
   *  fixed label may be suppressed if the body has its own heading).
   *  False for the auto-populated "This week" section which always
   *  keeps its label. */
  authorable: boolean
}

export function ImportantPanelContent({
  welcomeBody,
  notesBody,
  focusOverride,
  className,
}: ContentProps) {
  const sections: SectionConfig[] = [
    { title: 'Welcome',   body: welcomeBody, authorable: true  },
    { title: 'This week', body: null, override: focusOverride, authorable: false },
    { title: 'Notes',     body: notesBody,   authorable: true  },
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
        {sections.map(({ title, body, override, authorable }, i) => {
          const doc = authorable ? tryParseDoc(body ?? null) : null
          const hasAuthoredContent = authorable && (doc ? docHasContent(doc) : !!body)
          // Suppress the fixed eyebrow only when the body will render
          // its own leading heading. Bodies that begin with paragraphs
          // still get the eyebrow so members know which section they
          // are reading.
          const suppressEyebrow = authorable && docLeadsWithHeading(doc)
          return (
            <React.Fragment key={title}>
              {i > 0 && <div className="h-px" style={{ background: 'rgba(0,0,0,0.06)' }} />}
              <div>
                {!suppressEyebrow && (
                  <p className="mb-1.5 text-[13px] font-semibold text-navy-900">{title}</p>
                )}
                {override !== undefined ? (
                  override
                ) : hasAuthoredContent || body ? (
                  <PanelBody content={body} />
                ) : (
                  <p className="text-[12.5px] leading-relaxed text-black italic">
                    Nothing added yet.
                  </p>
                )}
              </div>
            </React.Fragment>
          )
        })}
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
