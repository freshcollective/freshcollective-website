/**
 * World Guide — shared types + design tokens + Markdown renderer.
 *
 * The World Guide is a lightweight governance CMS. Content is stored
 * as Markdown-shaped text and rendered on read; no rich-text editor
 * dependency is introduced.
 *
 * The renderer here handles the subset of Markdown that governance
 * documents actually use: paragraphs, H2/H3 headings, bulleted +
 * numbered lists, blockquotes, tables, links, bold and italic
 * emphasis, and a small callout syntax (`> [!note] ...`). This is
 * intentionally not a full CommonMark parser — anything more
 * elaborate should be a real dependency, deliberately chosen.
 */

// ---------------------------------------------------------------------------
// Types (mirror app/admin/world_guide/schemas.py)
// ---------------------------------------------------------------------------

export interface VersionSummary {
  id: string
  version_number: string
  status: 'draft' | 'published' | 'archived'
  effective_date: string | null
  published_at: string | null
  published_by_name: string | null
  last_edited_by_name: string | null
  updated_at: string
}

export interface VersionDetail {
  id: string
  document_id: string
  version_number: string
  status: 'draft' | 'published' | 'archived'
  effective_date: string | null
  why_this_exists: string | null
  what_this_covers: string | null
  main_content: string | null
  whats_changed: string | null
  published_at: string | null
  published_by_name: string | null
  last_edited_by_name: string | null
  created_at: string
  updated_at: string
}

export interface DocumentListRow {
  id: string
  slug: string
  title: string
  category: string
  audience: string
  status: 'draft' | 'published' | 'archived'
  current_version_number: string | null
  effective_date: string | null
  updated_at: string
  last_updated_by_name: string | null
}

export interface DocumentSummary {
  id: string
  slug: string
  title: string
  category: string
  status: 'draft' | 'published' | 'archived'
  current_version_number: string | null
  updated_at: string
}

export interface DocumentDetail {
  id: string
  slug: string
  title: string
  category: string
  audience: string
  summary: string | null
  reading_time_minutes: number | null
  author_name: string | null
  author_user_id: string | null
  archived_at: string | null
  current_version_id: string | null
  created_at: string
  updated_at: string
  versions: VersionSummary[]
  current_draft: VersionDetail | null
  current_published: VersionDetail | null
}

export interface WorldGuideOverview {
  published_count: number
  draft_count: number
  archived_count: number
  last_published: DocumentSummary | null
  recently_updated: DocumentSummary[]
}

export interface PublicDocumentCard {
  slug: string
  title: string
  category: string
  audience: string
  summary: string | null
  reading_time_minutes: number | null
  version_number: string
  effective_date: string | null
}

export interface PublicDocumentDetail {
  slug: string
  title: string
  category: string
  audience: string
  summary: string | null
  reading_time_minutes: number | null
  version_number: string
  effective_date: string | null
  published_at: string | null
  updated_at: string
  why_this_exists: string | null
  what_this_covers: string | null
  main_content: string | null
  whats_changed: string | null
  related: { slug: string; title: string; category: string }[]
}

// ---------------------------------------------------------------------------
// Design tokens — aligned with the Fresh Collective palette.
// White surfaces, navy headings, teal for primary accents, gold used
// sparingly for emphasis on published/version chrome.
// ---------------------------------------------------------------------------

export const WG = {
  pageBg:      '#FFFFFF',
  surfaceBg:   '#FAFBFC',      // subtle off-white for large writing areas
  cardBg:      '#FFFFFF',
  ink:         '#0F172A',      // black-ish for body text
  inkStrong:   '#152236',      // navy-900 for headings
  inkMuted:    'rgba(15, 23, 42, 0.62)',
  inkSofter:   'rgba(15, 23, 42, 0.42)',
  divider:     '1px solid rgba(15, 23, 42, 0.08)',
  hairline:    '1px solid rgba(15, 23, 42, 0.05)',
  teal:        '#2E8584',      // teal-600
  tealSoft:    'rgba(46, 133, 132, 0.10)',
  navy:        '#152236',      // navy-900
  navySoft:    'rgba(21, 34, 54, 0.06)',
  gold:        '#BF9830',      // gold-400 — used sparingly
  goldSoft:    'rgba(191, 152, 48, 0.10)',
  danger:      '#a63c30',
  cardShadow:  '0 1px 2px rgba(15,23,42,0.04)',
  cardShadowLg:'0 4px 20px rgba(15,23,42,0.06), 0 2px 4px rgba(15,23,42,0.04)',
  // Kept for source-compat with existing pages; the values map onto
  // the refreshed palette so callers don't break.
  accent:      '#2E8584',
  accentSoft:  'rgba(46, 133, 132, 0.10)',
}

export const CATEGORY_LABEL: Record<string, string> = {
  governance: 'Governance',
  members:    'Members',
  creators:   'Creators',
  platform:   'Platform',
  other:      'Other',
}

export const AUDIENCE_LABEL: Record<string, string> = {
  everyone:       'Everyone',
  members:        'Members',
  creators:       'Creators',
  platform_owner: 'Platform Owner',
  other:          'Other',
}

// ---------------------------------------------------------------------------
// Markdown → sanitized HTML renderer
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Enter-key list continuation
// ---------------------------------------------------------------------------

/**
 * Result of examining the current line to decide what pressing Enter
 * should do. Kept as a pure function so the editor's keydown handler
 * can stay thin and so the behaviour is trivially testable.
 *
 *   - ``continue`` — insert a newline followed by the given prefix
 *     (e.g. `\n- ` or `\n3. `). The cursor lands after the prefix.
 *   - ``end`` — the current list item is empty; delete the marker
 *     itself so the writer lands on a plain blank line, ending the
 *     list.
 *   - ``default`` — the line is not part of a list-shape; browser
 *     handles Enter normally.
 */
export type ContinueResult =
  | { kind: 'continue'; insert: string }
  | { kind: 'end'; markerLength: number }
  | { kind: 'default' }


/**
 * Given the text from the start of the current line up to the cursor,
 * decide whether Enter should continue a Markdown list-shape.
 *
 * Recognises, in order:
 *   - Task-list items `- [ ] ...` / `- [x] ...`
 *   - Bullet items `- ...`, `* ...`, `+ ...`
 *   - Numbered items `n. ...` (increments)
 *   - Blockquotes `> ...`
 *
 * Nested indentation is preserved verbatim. Completed checklist
 * state is never carried forward — a new task-list continuation is
 * always `- [ ] `.
 */
export function continueListOnEnter(lineBeforeCursor: string): ContinueResult {
  // Task-list — evaluated before ordinary bullets so the `[ ]` slice
  // doesn't get eaten by the bullet rule.
  const check = /^(\s*)([-*+])\s+\[(?: |x|X)\]\s?(.*)$/.exec(lineBeforeCursor)
  if (check) {
    const [full, indent, marker, rest] = check
    if (rest.trim().length === 0) {
      return { kind: 'end', markerLength: full.length - rest.length }
    }
    return { kind: 'continue', insert: `\n${indent}${marker} [ ] ` }
  }
  // Bullet
  const bul = /^(\s*)([-*+])\s(.*)$/.exec(lineBeforeCursor)
  if (bul) {
    const [full, indent, marker, rest] = bul
    if (rest.trim().length === 0) {
      return { kind: 'end', markerLength: full.length - rest.length }
    }
    return { kind: 'continue', insert: `\n${indent}${marker} ` }
  }
  // Numbered — capture the digit(s) and increment.
  const num = /^(\s*)(\d+)\.\s(.*)$/.exec(lineBeforeCursor)
  if (num) {
    const [full, indent, n, rest] = num
    if (rest.trim().length === 0) {
      return { kind: 'end', markerLength: full.length - rest.length }
    }
    const next = parseInt(n, 10) + 1
    return { kind: 'continue', insert: `\n${indent}${next}. ` }
  }
  // Blockquote — `> ...` or `> ` alone. The stored line uses either
  // one space (from `> body`) or none (from `>` on its own).
  const bq = /^(\s*)>\s?(.*)$/.exec(lineBeforeCursor)
  if (bq) {
    const [full, indent, rest] = bq
    if (rest.trim().length === 0) {
      return { kind: 'end', markerLength: full.length }
    }
    return { kind: 'continue', insert: `\n${indent}> ` }
  }
  return { kind: 'default' }
}


// ---------------------------------------------------------------------------
// Markdown import — split a pasted document into the four sections.
// ---------------------------------------------------------------------------

export interface ImportResult {
  why_this_exists: string
  what_this_covers: string
  main_content: string
  whats_changed: string
  /** Per-section trace of which heading (if any) mapped into it. */
  matched: Record<
    'why_this_exists' | 'what_this_covers' | 'main_content' | 'whats_changed',
    string | null
  >
  /** True when nothing matched — everything landed in main_content. */
  fallback_all_to_main: boolean
}

type SectionKey = 'why_this_exists' | 'what_this_covers' | 'main_content' | 'whats_changed'

/** Aliases → canonical section key. Comparison is case-insensitive and
 *  space-tolerant so pasted content from ChatGPT / Notion / editors
 *  with lightly different heading wording still finds its home. */
const SECTION_ALIASES: [pattern: RegExp, key: SectionKey][] = [
  [/^why (this|the) (exists|matters)|purpose|context$/i, 'why_this_exists'],
  [/^why|about|introduction|intro$/i, 'why_this_exists'],
  [/^what (this|the) covers|scope|coverage|what.?s covered|in scope$/i, 'what_this_covers'],
  [/^main content|content|policy|body|the policy|details|full text$/i, 'main_content'],
  [/^what.?s changed|changes|changelog|release notes|history$/i, 'whats_changed'],
]

/** Return the canonical section key for a heading title, or null if
 *  the title does not resemble any section. */
function matchSection(title: string): SectionKey | null {
  const t = title.trim().toLowerCase()
  for (const [re, key] of SECTION_ALIASES) {
    if (re.test(t)) return key
  }
  return null
}

/**
 * Parse a Markdown document into the four World Guide sections.
 *
 * Strategy:
 *   - Scan for top-level `#` and `##` headings.
 *   - If a heading matches one of the section aliases, everything
 *     between that heading and the next matching (or the end of the
 *     document) becomes that section's content.
 *   - Content before any recognised heading, plus content under
 *     unmatched headings, becomes ``main_content``.
 *   - When no headings match at all, the entire input is placed in
 *     ``main_content`` verbatim — the caller can then split it by
 *     hand.
 */
export function parseImportedMarkdown(markdown: string): ImportResult {
  const src = (markdown ?? '').replace(/\r\n?/g, '\n')
  const lines = src.split('\n')

  const buckets: Record<SectionKey, string[]> = {
    why_this_exists: [], what_this_covers: [], main_content: [], whats_changed: [],
  }
  const matched: ImportResult['matched'] = {
    why_this_exists: null, what_this_covers: null, main_content: null, whats_changed: null,
  }

  let current: SectionKey = 'main_content'
  let anyMatched = false

  for (const raw of lines) {
    const h = /^(#{1,2})\s+(.+)$/.exec(raw)
    if (h) {
      const title = h[2].trim()
      const mk = matchSection(title)
      if (mk) {
        current = mk
        matched[mk] = title
        anyMatched = true
        continue // omit the heading itself from the bucketed content
      }
    }
    buckets[current].push(raw)
  }

  function pack(arr: string[]): string {
    return arr.join('\n').replace(/^\n+|\n+$/g, '').trim()
  }

  return {
    why_this_exists:  pack(buckets.why_this_exists),
    what_this_covers: pack(buckets.what_this_covers),
    main_content:     pack(buckets.main_content),
    whats_changed:    pack(buckets.whats_changed),
    matched,
    fallback_all_to_main: !anyMatched,
  }
}


function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function inlineMd(s: string): string {
  // Order matters: escape first, then rewrite inline patterns.
  let out = escapeHtml(s)
  // Images ![alt](url) — must come before links so ! isn't stripped
  out = out.replace(
    /!\[([^\]]*)\]\(([^)\s]+)\)/g,
    (_m, alt, url) => {
      const safeUrl = /^https?:\/\/|^\//.test(url) ? url : '#'
      return `<img src="${safeUrl}" alt="${alt}" style="max-width:100%;height:auto;border-radius:6px;margin:12px 0;" />`
    },
  )
  // Bold **x** (do before italic so ** binds tighter than *)
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  // Italic *x* — avoid matching inside **
  out = out.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
  // Inline code `x`
  out = out.replace(/`([^`\n]+)`/g, '<code>$1</code>')
  // Links [text](url) — escape both text and url paths already escaped by escapeHtml
  out = out.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    (_m, text, url) => {
      const safeUrl = /^https?:\/\/|^\/|^mailto:/.test(url) ? url : '#'
      return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${text}</a>`
    },
  )
  return out
}

function renderTable(rows: string[]): string {
  // rows: an array of "|c|c|c|" lines. Second line may be alignment "|:--|:--|".
  const cells = rows.map((r) =>
    r
      .trim()
      .replace(/^\||\|$/g, '')
      .split('|')
      .map((c) => c.trim()),
  )
  if (cells.length === 0) return ''
  const hasAlign = cells.length > 1 && cells[1].every((c) => /^:?-+:?$/.test(c))
  const header = cells[0]
  const bodyRows = hasAlign ? cells.slice(2) : cells.slice(1)
  const thead = `<thead><tr>${header
    .map((h) => `<th>${inlineMd(h)}</th>`).join('')}</tr></thead>`
  const tbody = `<tbody>${bodyRows
    .map((row) => `<tr>${row.map((c) => `<td>${inlineMd(c)}</td>`).join('')}</tr>`)
    .join('')}</tbody>`
  return `<table>${thead}${tbody}</table>`
}

/**
 * Convert Markdown-shaped text to HTML.
 *
 * Handles:
 *   # / ## / ### headings
 *   Unordered lists (- ...) and ordered lists (1. ...)
 *   Task lists (- [ ] / - [x])
 *   Numbered-heading conventions (e.g. `## 1.2 Section title` → h2 with
 *     the leading `1.2 ` preserved as visible text)
 *   Fenced code blocks (```)
 *   Horizontal rules (--- or ***)
 *   Blockquotes (>) and callouts (> [!note] Title\n> body)
 *   Tables (| col | col |)
 *   Paragraphs (blank-line separated)
 *   Inline bold, italic, code, links, images (![alt](url))
 *
 * Falls back to safe escaped text for everything else.
 */
export function renderMarkdown(text: string): string {
  if (!text || !text.trim()) return ''
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const html: string[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    // Blank line — paragraph break, skip.
    if (!line.trim()) { i++; continue }

    // Fenced code block
    const fence = /^```(\w*)\s*$/.exec(line.trim())
    if (fence) {
      const body: string[] = []
      i++
      while (i < lines.length && !/^```/.test(lines[i].trim())) {
        body.push(lines[i])
        i++
      }
      if (i < lines.length) i++ // consume closing fence
      html.push(`<pre><code>${escapeHtml(body.join('\n'))}</code></pre>`)
      continue
    }

    // Horizontal rule
    if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) {
      html.push('<hr />')
      i++
      continue
    }

    // Headings — leading digit-dot notation (e.g. `## 1.2 Something`) is
    // preserved verbatim as visible text so governance numbering renders
    // like "1.2 Something" without needing a separate span.
    const h = /^(#{1,3})\s+(.+)$/.exec(line)
    if (h) {
      const lvl = h[1].length
      html.push(`<h${lvl}>${inlineMd(h[2])}</h${lvl}>`)
      i++
      continue
    }

    // Tables — at least a header row followed by a delimiter row.
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      const block: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        block.push(lines[i])
        i++
      }
      html.push(renderTable(block))
      continue
    }

    // Blockquotes + callouts
    if (line.trim().startsWith('>')) {
      const block: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        block.push(lines[i].replace(/^\s*>\s?/, ''))
        i++
      }
      const first = block[0] ?? ''
      const callout = /^\[!(note|tip|warning|info)\]\s*(.*)$/i.exec(first)
      if (callout) {
        const kind = callout[1].toLowerCase()
        const title = callout[2].trim()
        const body = block.slice(1).join('\n').trim()
        html.push(
          `<aside class="wg-callout wg-callout-${kind}">` +
          (title ? `<div class="wg-callout-title">${inlineMd(title)}</div>` : '') +
          (body ? `<div class="wg-callout-body">${renderMarkdown(body)}</div>` : '') +
          `</aside>`
        )
        continue
      }
      html.push(`<blockquote>${renderMarkdown(block.join('\n'))}</blockquote>`)
      continue
    }

    // Task list (checklist) — must come before generic bullet list.
    if (/^\s*[-*]\s+\[(?: |x|X)\]\s+/.test(line)) {
      const items: { done: boolean; body: string }[] = []
      while (i < lines.length && /^\s*[-*]\s+\[(?: |x|X)\]\s+/.test(lines[i])) {
        const m = /^\s*[-*]\s+\[( |x|X)\]\s+(.*)$/.exec(lines[i])!
        items.push({ done: m[1].toLowerCase() === 'x', body: m[2] })
        i++
      }
      html.push(
        '<ul class="wg-checklist" style="list-style:none;margin-left:0;padding-left:0;">' +
        items.map((it) =>
          `<li style="display:flex;gap:8px;align-items:flex-start;margin:4px 0;">` +
          `<input type="checkbox" disabled${it.done ? ' checked' : ''} style="margin-top:4px;" />` +
          `<span${it.done ? ' style="text-decoration:line-through;opacity:0.65;"' : ''}>${inlineMd(it.body)}</span>` +
          `</li>`
        ).join('') +
        '</ul>'
      )
      continue
    }

    // Unordered list
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ''))
        i++
      }
      html.push(`<ul>${items.map((it) => `<li>${inlineMd(it)}</li>`).join('')}</ul>`)
      continue
    }

    // Ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ''))
        i++
      }
      html.push(`<ol>${items.map((it) => `<li>${inlineMd(it)}</li>`).join('')}</ol>`)
      continue
    }

    // Paragraph — collect until blank line.
    const para: string[] = [line]
    i++
    while (
      i < lines.length && lines[i].trim() &&
      !/^(#{1,3}\s+|>|\s*[-*]\s+|\s*\d+\.\s+|\||```|\s*(---+|\*\*\*+)\s*$)/.test(lines[i])
    ) {
      para.push(lines[i])
      i++
    }
    html.push(`<p>${inlineMd(para.join(' '))}</p>`)
  }
  return html.join('\n')
}
