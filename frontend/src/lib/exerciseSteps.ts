/**
 * Server-safe helper for the ``exercise`` block content column.
 *
 * Exercise is now a specialised Content block: the body is stored as a
 * TipTap JSON document (identical shape to a Content block), and an
 * optional title lives in ``block.label``.
 *
 * Historical rows still hold a JSON envelope of the shape
 * ``{"exercise":{"steps":["Step 1","Step 2",…]}}``. ``exerciseContentToRichText``
 * migrates those legacy envelopes to a TipTap ordered-list document at
 * read time so both the creator editor and the member-facing renderers
 * see one canonical shape. On the next save, the migrated row is
 * persisted back as TipTap JSON — the legacy envelope quietly
 * disappears without a data migration.
 *
 * This module lives outside the client-only ``BlockEditorShared``
 * bundle so both the member step page (Server Component) and the
 * creator editor (Client Component) can call it.
 */


/**
 * Convert an exercise block's stored content into a TipTap JSON
 * document string.
 *
 * Rules:
 *   - Empty / null → empty string (renderers show the placeholder).
 *   - Anything that already parses as a TipTap ``doc`` → returned
 *     verbatim.
 *   - Legacy JSON envelope ``{"exercise":{"steps":[…]}}`` → converted
 *     to a TipTap doc containing a single ``orderedList`` whose items
 *     are the step strings.
 *   - Anything else (plain text, malformed) → returned verbatim so
 *     ``parseRichContent`` can fall back to plain-paragraph handling.
 */
export function exerciseContentToRichText(content: string | null | undefined): string {
  if (!content || !content.trim()) return ''
  try {
    const parsed = JSON.parse(content) as {
      type?: string
      exercise?: { steps?: unknown[] }
    }
    if (parsed?.type === 'doc') return content
    if (parsed?.exercise?.steps && Array.isArray(parsed.exercise.steps)) {
      const steps = parsed.exercise.steps.filter((s): s is string => typeof s === 'string' && s.trim().length > 0)
      if (steps.length === 0) return ''
      const doc = {
        type: 'doc',
        content: [{
          type: 'orderedList',
          content: steps.map((s) => ({
            type: 'listItem',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: s }] }],
          })),
        }],
      }
      return JSON.stringify(doc)
    }
  } catch {
    // fall through
  }
  return content
}
