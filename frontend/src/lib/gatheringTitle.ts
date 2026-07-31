/**
 * Session-theme extraction for Gathering titles.
 *
 * Creators often prefix Gathering titles with the Collective name or
 * a session-shape (e.g. "Saturday EMBODY Session — Radiance"). On
 * compact cards where the Collective name and gathering type appear
 * as separate metadata lines, echoing them inside the title creates
 * visual noise.
 *
 * ``extractSessionTheme`` returns just the *theme* portion — the
 * segment after a clear "title — theme" separator — so cards can
 * present the theme as the primary title without the repetition.
 * Titles that don't follow that pattern are returned unchanged.
 */

// Only separators surrounded by whitespace count — this keeps
// hyphenated words like "post-work" intact. Ordered from most to
// least specific.
const SEPARATORS = [' — ', ' – ', ' - ', ': '] as const

/**
 * Extract the session theme from a Gathering title. Splits on the
 * *last* whitespace-flanked em-dash / en-dash / hyphen / colon and
 * returns whatever follows. Titles without any such separator (e.g.
 * "Grove Circle") are returned unchanged.
 */
export function extractSessionTheme(title: string): string {
  const trimmed = title.trim()
  for (const sep of SEPARATORS) {
    const idx = trimmed.lastIndexOf(sep)
    if (idx > 0 && idx + sep.length < trimmed.length) {
      const after = trimmed.slice(idx + sep.length).trim()
      if (after) return after
    }
  }
  return trimmed
}
