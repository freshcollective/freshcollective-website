import React from 'react'

import { extractHeadings } from '@/lib/guides'
import { safeHref } from '@/lib/safeHref'
import { SERIF_HEADING } from './serif'

/**
 * A Guide's body, rendered.
 *
 * The display half of a contract whose other half is
 * ``backend/app/services/guide_body.py``. The two lists must match
 * exactly, and ``test_guides.py`` reads :data:`RENDERED_TAGS` out of
 * this file to prove it — because the two ways they can drift fail
 * differently and both look like the author's fault. A tag the
 * sanitiser keeps and this renderer drops vanishes at display time,
 * which reads as lost work; a tag this renderer handles and the
 * sanitiser strips vanishes at save time, which is worse because the
 * author watched it happen.
 *
 * **No ``dangerouslySetInnerHTML``.** The stored HTML is already
 * sanitised server-side, so this is belt and braces rather than the
 * only protection — but building React nodes means a tag that somehow
 * survived the sanitiser still cannot become live markup here.
 *
 * Typography is an article's, not a card's: ~17px body at 1.8,
 * serif H2s, and a first paragraph one step larger as a lead. That is
 * why this is not ``MarkdownBody``, which renders About-page content
 * at 15px with a sans H2 and has no block quote or image at all.
 */

/**
 * Every tag this component renders. Read by a backend test — keep the
 * literal array shape (single-quoted strings in one `[...]`).
 */
export const RENDERED_TAGS = [
  'p', 'br',
  'h2', 'h3',
  'ul', 'ol', 'li',
  'strong', 'b', 'em', 'i',
  'a',
  'blockquote',
  'img',
] as const

// ---------------------------------------------------------------------------
// Inline
// ---------------------------------------------------------------------------

function decodeEntities(html: string): string {
  return html
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    // Last, or "&amp;lt;" would decode twice and reintroduce a tag.
    .replace(/&amp;/g, '&')
}

/**
 * Bold, italic, links, line breaks and text.
 *
 * ``b``/``i`` are handled alongside ``strong``/``em`` because the
 * sanitiser allows them: the editor emits the semantic pair, but text
 * pasted from a word processor arrives as the presentational one, and
 * dropping it would silently lose an author's emphasis.
 */
function renderInline(html: string, keyBase: string): React.ReactNode {
  const nodes: React.ReactNode[] = []
  const re =
    /<(?:strong|b)[^>]*>([\s\S]*?)<\/(?:strong|b)>|<(?:em|i)[^>]*>([\s\S]*?)<\/(?:em|i)>|<a[^>]+href="([^"]*)"[^>]*>([\s\S]*?)<\/a>|<br\s*\/?>|<[^>]+>|([^<]+)/g
  let m: RegExpExecArray | null
  let i = 0

  while ((m = re.exec(html)) !== null) {
    const k = `${keyBase}-${i++}`
    if (m[1] !== undefined) {
      nodes.push(
        <strong key={k} className="font-semibold text-navy-950">
          {decodeEntities(m[1])}
        </strong>,
      )
    } else if (m[2] !== undefined) {
      nodes.push(<em key={k}>{decodeEntities(m[2])}</em>)
    } else if (m[3] !== undefined) {
      const href = safeHref(decodeEntities(m[3]))
      const text = decodeEntities(m[4].replace(/<[^>]*>/g, ''))
      if (href) {
        const external = /^https?:\/\//i.test(href)
        nodes.push(
          <a
            key={k}
            href={href}
            {...(external
              ? { target: '_blank', rel: 'noopener noreferrer' }
              : {})}
            className="text-teal-700 underline decoration-teal-300 underline-offset-[3px] transition-colors hover:text-teal-800 hover:decoration-teal-500"
          >
            {text}
          </a>,
        )
      } else {
        // A link we will not follow still keeps its words.
        nodes.push(<React.Fragment key={k}>{text}</React.Fragment>)
      }
    } else if (m[0].toLowerCase().startsWith('<br')) {
      nodes.push(<br key={k} />)
    } else if (m[5] !== undefined) {
      nodes.push(<React.Fragment key={k}>{decodeEntities(m[5])}</React.Fragment>)
    }
  }
  return nodes
}

// ---------------------------------------------------------------------------
// Blocks
// ---------------------------------------------------------------------------

type Block =
  | { tag: 'h2' | 'h3' | 'p' | 'blockquote'; inner: string }
  | { tag: 'ul' | 'ol'; items: string[] }
  | { tag: 'img'; src: string; alt: string }

const BLOCK_TAGS = ['h2', 'h3', 'p', 'ul', 'ol', 'blockquote']

/**
 * Split the stored HTML into top-level blocks.
 *
 * Walks to the matching close tag rather than using a lazy regex, so
 * a ``<blockquote>`` holding a ``<p>`` — which is exactly what TipTap
 * emits — is one block rather than two overlapping ones.
 */
function splitBlocks(html: string): Block[] {
  const blocks: Block[] = []
  let i = 0

  while (i < html.length) {
    if (html[i] !== '<') { i++; continue }

    const selfClosing = html.slice(i).match(/^<img\b[^>]*>/i)
    if (selfClosing) {
      const tag = selfClosing[0]
      const src = /\bsrc="([^"]*)"/i.exec(tag)?.[1] ?? ''
      const alt = /\balt="([^"]*)"/i.exec(tag)?.[1] ?? ''
      if (src) blocks.push({ tag: 'img', src, alt: decodeEntities(alt) })
      i += tag.length
      continue
    }

    const open = html.slice(i).match(/^<([a-z][a-z0-9]*)[^>]*>/i)
    if (!open || !BLOCK_TAGS.includes(open[1].toLowerCase())) { i++; continue }

    const tag = open[1].toLowerCase()
    const closeTag = `</${tag}>`
    let depth = 1
    let j = i + open[0].length
    while (j < html.length && depth > 0) {
      if (html.slice(j, j + tag.length + 1).toLowerCase() === `<${tag}`) {
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

    const inner = html.slice(i + open[0].length, j)
    i = j + closeTag.length

    if (tag === 'ul' || tag === 'ol') {
      const items: string[] = []
      const liRe = /<li[^>]*>([\s\S]*?)<\/li>/gi
      let li: RegExpExecArray | null
      while ((li = liRe.exec(inner)) !== null) {
        // TipTap wraps each item's text in a <p>; unwrap it so the
        // bullet and its text sit on one line.
        const p = /<p[^>]*>([\s\S]*?)<\/p>/i.exec(li[1])
        items.push(p ? p[1] : li[1])
      }
      if (items.length) blocks.push({ tag, items })
    } else if (tag === 'blockquote') {
      // The quote's own paragraphs are flattened: a pull quote is one
      // statement, and rendering nested <p> inside it would stack the
      // gold rule beside two separately-spaced blocks.
      blocks.push({ tag: 'blockquote', inner: inner.replace(/<\/?p[^>]*>/gi, ' ') })
    } else if (tag === 'p') {
      if (inner.trim()) blocks.push({ tag: 'p', inner })
    } else {
      blocks.push({ tag: tag as 'h2' | 'h3', inner })
    }
  }

  return blocks
}

/**
 * Everything about a block that depends on the blocks around it.
 *
 * Computed in one pass up front rather than by mutating counters
 * inside the render callback: a variable reassigned from inside
 * ``map`` is reassigned during render, which is exactly the pattern
 * that produces inconsistent output across re-renders and which the
 * React compiler refuses. Pure function, two derived facts.
 *
 *   ``id``    the heading's anchor, taken from ``extractHeadings`` so
 *             the "On this page" box and the body cannot disagree —
 *             including about a Guide that uses the same wording
 *             twice, where deriving ids separately gave both
 *             headings one id and left the second contents entry
 *             pointing at the first.
 *   ``lead``  the first paragraph of the article, which renders one
 *             step larger. The first paragraph *of the article*, not
 *             the first after every heading.
 */
function decorate(
  blocks: Block[],
  headingIds: string[],
): Array<{ block: Block; id?: string; lead?: boolean }> {
  let h2Index = 0
  let seenParagraph = false
  return blocks.map((block) => {
    if (block.tag === 'h2') return { block, id: headingIds[h2Index++] }
    if (block.tag === 'p' && !seenParagraph) {
      seenParagraph = true
      return { block, lead: true }
    }
    return { block }
  })
}

// ---------------------------------------------------------------------------

export default function GuideBody({ html }: { html: string }) {
  const source = html ?? ''
  const decorated = decorate(
    splitBlocks(source),
    extractHeadings(source).map((h) => h.id),
  )

  return (
    <div className="guide-body">
      {decorated.map(({ block: b, id, lead }, i) => {
        const k = `gb-${i}`

        if (b.tag === 'h2') {
          return (
            <h2
              key={k}
              id={id}
              className="mt-12 mb-4 text-[26px] font-bold leading-[1.2] tracking-[-0.02em] text-navy-950 first:mt-0 md:text-[28px]"
              style={SERIF_HEADING}
            >
              {renderInline(b.inner, k)}
            </h2>
          )
        }

        if (b.tag === 'h3') {
          return (
            <h3
              key={k}
              className="mt-8 mb-3 text-[20px] font-semibold leading-[1.3] text-navy-950"
              style={SERIF_HEADING}
            >
              {renderInline(b.inner, k)}
            </h3>
          )
        }

        if (b.tag === 'p') {
          return (
            <p
              key={k}
              className={
                lead
                  ? 'mb-6 text-[19px] leading-[1.72] text-navy-950 md:text-[20px]'
                  : 'mb-6 text-[17px] leading-[1.8] text-navy-950'
              }
            >
              {renderInline(b.inner, k)}
            </p>
          )
        }

        if (b.tag === 'ul') {
          return (
            <ul key={k} className="mb-6 list-disc space-y-2 pl-6 marker:text-navy-400">
              {b.items.map((item, idx) => (
                <li key={idx} className="pl-1 text-[17px] leading-[1.8] text-navy-950">
                  {renderInline(item, `${k}-${idx}`)}
                </li>
              ))}
            </ul>
          )
        }

        if (b.tag === 'ol') {
          return (
            <ol key={k} className="mb-6 list-decimal space-y-2 pl-6 marker:text-navy-400">
              {b.items.map((item, idx) => (
                <li key={idx} className="pl-1 text-[17px] leading-[1.8] text-navy-950">
                  {renderInline(item, `${k}-${idx}`)}
                </li>
              ))}
            </ol>
          )
        }

        if (b.tag === 'blockquote') {
          // A pull quote, not an indented paragraph: thin gold rule,
          // italic serif, one step up.
          return (
            <blockquote
              key={k}
              className="my-9 border-l-[3px] border-gold-400 py-1 pl-6 font-serif text-[20px] italic leading-[1.5] text-navy-700 md:text-[21px]"
            >
              {renderInline(b.inner, k)}
            </blockquote>
          )
        }

        // An inline image. Plain <img> rather than next/image: the
        // source is a runtime value from the database, and configuring
        // remote patterns for body images buys optimisation at the
        // cost of a build-time allowlist that would silently break the
        // day the media host changes.
        //
        // Checked explicitly rather than left as a fall-through, so
        // adding a block kind without rendering it is a type error
        // here instead of an image with no source in production.
        if (b.tag === 'img') {
          return (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={k}
              src={b.src}
              alt={b.alt}
              loading="lazy"
              className="my-8 h-auto w-full rounded-xl"
            />
          )
        }

        return null
      })}
    </div>
  )
}
