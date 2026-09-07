/**
 * Text helpers for the IslandDetailModal, factored out so they can be
 * imported into the Node-native test runner (Node's ``--experimental-
 * strip-types`` loader handles ``.ts`` but not ``.tsx``).
 */

/**
 * Split raw Atlas Entry text into paragraphs on blank-line boundaries.
 * Empty paragraphs are dropped; per-paragraph whitespace is trimmed.
 * Runs of blank lines collapse to a single break. Single ``\n``
 * inside a paragraph is preserved as a soft break, so hard-wrapped
 * admin input still reads correctly.
 */
export function splitParagraphs(text: string | null): string[] {
  if (!text) return []
  return text
    .replace(/\r\n/g, '\n')
    .split(/\n\s*\n/)
    .map((p) => p.replace(/\s+\n/g, '\n').trim())
    .filter((p) => p.length > 0)
}
