/**
 * Pure helpers for reading TipTap-shaped rich-text documents.
 *
 * Server-safe (no React, no client-only deps) so they can back
 * both editor logic (Creator Studio) and renderers (Member Hub)
 * without pulling either into the wrong bundle.
 *
 * The TipTap JSON shape is deliberately structural — walk it,
 * don't parse it as HTML. Two callers today:
 *
 *   * ``PanelBody`` in ``components/spaces/ImportantPanel.tsx`` —
 *     safely renders the doc for the Member Hub.
 *   * ``ImportantPanelContent`` — decides whether to render the
 *     fixed "Welcome" / "Notes" eyebrow above the body, or defer
 *     to the Creator's own leading heading.
 */

export interface RichTextMark {
  type: string
  attrs?: { href?: string; target?: string; rel?: string }
}

export interface RichTextNode {
  type: string
  attrs?: Record<string, unknown>
  content?: RichTextNode[]
  text?: string
  marks?: RichTextMark[]
}

/** Parse a stored value into a TipTap ``doc`` node, or null if it
 *  isn't valid JSON with the right shape. Plain-text bodies (older
 *  rows saved before the TipTap editor shipped) return null so the
 *  caller can fall back to a plain-text render. */
export function tryParseDoc(value: string | null | undefined): RichTextNode | null {
  if (!value) return null
  try {
    const parsed = JSON.parse(value) as RichTextNode
    return parsed?.type === 'doc' ? parsed : null
  } catch {
    return null
  }
}


/** True when the doc has any renderable content — a heading, a
 *  non-empty paragraph, a list, etc. Empty ``doc`` and docs whose
 *  only content is empty paragraphs both count as empty. Used by
 *  the save path so an editor left completely blank doesn't
 *  persist a phantom TipTap payload. */
export function docHasContent(doc: RichTextNode | null): boolean {
  if (!doc || doc.type !== 'doc' || !doc.content) return false
  return doc.content.some(nodeHasContent)
}


function nodeHasContent(node: RichTextNode): boolean {
  if (node.type === 'text') return (node.text ?? '').length > 0
  if (node.type === 'hardBreak') return false
  if (node.content && node.content.length > 0) {
    return node.content.some(nodeHasContent)
  }
  // Structural nodes with no children — nothing to render.
  return false
}


/** True when the first non-empty block in the doc is a heading.
 *  Used by ``ImportantPanelContent`` to suppress the fixed
 *  "Welcome" / "Notes" eyebrow when the Creator has authored
 *  their own section title — avoiding two stacked titles above
 *  the same body. */
export function docLeadsWithHeading(doc: RichTextNode | null): boolean {
  if (!doc || doc.type !== 'doc' || !doc.content) return false
  for (const child of doc.content) {
    if (!nodeHasContent(child) && child.type !== 'heading') continue
    return child.type === 'heading'
  }
  return false
}
