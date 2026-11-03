/**
 * A formatted description, as text.
 *
 * Gathering and Gathering Series descriptions carry the creator's own
 * formatting — written in the same TipTap editor the Collective About
 * page uses, stored as HTML. Most surfaces that show a description are
 * not HTML: a card, a search result, a calendar link, a meta tag. A
 * card showing `<strong>Join us for an evening…</strong>` is the thing
 * this exists to prevent.
 *
 * One conversion, so there is no second stripping implementation to
 * drift. The server has the matching pair in
 * `backend/app/services/rich_text.py` — it owns sanitising and the
 * plain text for emails and calendar files, and this is the same rule
 * for the surfaces that render in the browser.
 *
 * Legacy descriptions pass through unchanged: plain text has no tags
 * to strip, so the many Gatherings written before formatting existed
 * read exactly as they always did.
 */

/** Tags whose boundaries are a break in the text. */
const BREAKS = /<\/?(br|p|div|h[1-6]|li|ul|ol)\b[^>]*>/gi

const NAMED_ENTITIES: Record<string, string> = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
  hellip: '…', mdash: '—', ndash: '–', rsquo: '’', lsquo: '‘',
  rdquo: '”', ldquo: '“',
}

function decodeEntities(text: string): string {
  return text
    // Numeric first, so "&#38;amp;" cannot become "&" and then be
    // decoded a second time into something else.
    .replace(/&#x([0-9a-f]+);/gi, (_, hex) =>
      String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(parseInt(dec, 10)))
    .replace(/&([a-z]+);/gi, (whole, name) =>
      NAMED_ENTITIES[String(name).toLowerCase()] ?? whole)
}

/**
 * The whole description as text, with its line structure kept.
 *
 * Paragraphs and list items stay on their own lines — a description
 * collapsed into one run-on line is a different kind of wrong from one
 * showing tags.
 */
export function richTextToPlain(value: string | null | undefined): string {
  if (!value) return ''
  const spaced = value.replace(BREAKS, '\n')
  // Every remaining tag goes. Nothing here is ever inserted as
  // markup — the safety boundary is the server's sanitiser; this is
  // for legibility.
  const stripped = spaced.replace(/<[^>]*>/g, '')
  return decodeEntities(stripped)
    .split('\n')
    .map((line) => line.replace(/[ \t]+/g, ' ').trim())
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/** Truncated on a word boundary, for a card or a meta description. */
export function richTextExcerpt(
  value: string | null | undefined, limit: number,
): string {
  const text = richTextToPlain(value).replace(/\s+/g, ' ').trim()
  if (text.length <= limit) return text
  const head = text.slice(0, limit)
  const cut = head.lastIndexOf(' ')
  // Only honour a word boundary that is not absurdly early, or a
  // description starting with one very long token returns a letter.
  return (cut >= Math.floor(limit * 0.75) ? head.slice(0, cut) : head)
    .trimEnd() + '…'
}

/** The opening line only — for a one-line summary row. */
export function richTextFirstLine(
  value: string | null | undefined, limit?: number,
): string | null {
  const first = richTextToPlain(value)
    .split('\n')
    .find((line) => line.trim().length > 0)
    ?.trim()
  if (!first) return null
  return limit != null && first.length > limit
    ? richTextExcerpt(first, limit)
    : first
}

/** Whether a stored description is formatted HTML rather than text. */
export function isFormattedDescription(
  value: string | null | undefined,
): boolean {
  return !!value && /^\s*<[a-z]/i.test(value)
}
