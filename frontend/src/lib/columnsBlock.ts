/**
 * Server-safe helpers for the ``columns`` step block.
 *
 * Columns blocks store a structured JSON envelope inside the existing
 * ``pathway_step_blocks.content`` text column — no schema changes:
 *
 *   {
 *     "layout": { "kind": "columns", "variant": "50-50" },
 *     "cells":  [
 *       { "content": "<TipTap HTML for column 1>" },
 *       { "content": "<TipTap HTML for column 2>" }
 *     ]
 *   }
 *
 * The envelope is deliberately split into ``layout`` and ``cells`` so
 * future layout kinds (cards, comparison table, 4-column grid) can
 * reuse the same shape with a different ``layout.kind`` / ``variant``.
 * Callers that only understand today's ``columns`` kind should fall
 * back to a generic side-by-side render when they encounter an
 * unfamiliar variant, so old rows never break.
 */


/** Every variant the ``columns`` layout kind currently supports. */
export type ColumnsVariant =
  | '50-50'
  | '33-33-33'
  | '25-25-25-25'
  | '66-33'
  | '33-66'

export const COLUMNS_VARIANTS: ColumnsVariant[] = [
  '50-50', '33-33-33', '25-25-25-25', '66-33', '33-66',
]

export interface ColumnsCell {
  content: string
}

export interface ColumnsPayload {
  layout: { kind: 'columns'; variant: ColumnsVariant }
  cells: ColumnsCell[]
}


/** Number of cells implied by each variant. */
export function cellCountForVariant(variant: ColumnsVariant): number {
  if (variant === '25-25-25-25') return 4
  if (variant === '33-33-33') return 3
  return 2
}


/** CSS ``grid-template-columns`` value for a variant. */
export function gridTemplateForVariant(variant: ColumnsVariant): string {
  if (variant === '50-50') return '1fr 1fr'
  if (variant === '33-33-33') return '1fr 1fr 1fr'
  if (variant === '25-25-25-25') return '1fr 1fr 1fr 1fr'
  if (variant === '66-33') return '2fr 1fr'
  if (variant === '33-66') return '1fr 2fr'
  return '1fr 1fr'
}


/** Human-readable label for the picker (used as tooltip / aria-label). */
export function labelForVariant(variant: ColumnsVariant): string {
  if (variant === '50-50') return 'Two equal columns'
  if (variant === '33-33-33') return 'Three equal columns'
  if (variant === '25-25-25-25') return 'Four equal columns'
  if (variant === '66-33') return 'Wide + narrow'
  if (variant === '33-66') return 'Narrow + wide'
  return variant
}


/** Compact ratio label (e.g. ``50 / 50``, ``2 / 1``) shown beneath the
 *  thumbnail in the layout picker. */
export function variantShortLabel(variant: ColumnsVariant): string {
  if (variant === '50-50') return '50 / 50'
  if (variant === '33-33-33') return 'Thirds'
  if (variant === '25-25-25-25') return 'Quarters'
  if (variant === '66-33') return '2 / 1'
  if (variant === '33-66') return '1 / 2'
  return variant
}


/** Empty envelope for freshly-inserted columns blocks. */
export function emptyColumnsPayload(variant: ColumnsVariant = '50-50'): ColumnsPayload {
  const n = cellCountForVariant(variant)
  return {
    layout: { kind: 'columns', variant },
    cells: Array.from({ length: n }, () => ({ content: '' })),
  }
}


/**
 * Parse a stored ``content`` string into a canonical ColumnsPayload.
 *
 * Accepts the modern envelope directly; anything unrecognised falls
 * back to an empty ``50-50`` layout so a corrupt row still opens
 * (rather than silently dropping the block).
 */
export function decodeColumns(content: string | null | undefined): ColumnsPayload {
  if (!content || !content.trim()) return emptyColumnsPayload()
  try {
    const parsed = JSON.parse(content) as Partial<ColumnsPayload>
    const kind = parsed?.layout?.kind
    const variant = parsed?.layout?.variant as ColumnsVariant | undefined
    if (kind === 'columns' && variant && COLUMNS_VARIANTS.includes(variant)) {
      const wanted = cellCountForVariant(variant)
      const raw = Array.isArray(parsed.cells) ? parsed.cells : []
      const cells: ColumnsCell[] = Array.from({ length: wanted }, (_, i) => ({
        content: typeof raw[i]?.content === 'string' ? raw[i]!.content : '',
      }))
      return { layout: { kind: 'columns', variant }, cells }
    }
  } catch {
    // fall through
  }
  return emptyColumnsPayload()
}


/** Serialise a payload back to the ``content`` column. */
export function encodeColumns(payload: ColumnsPayload): string {
  return JSON.stringify(payload)
}


/**
 * Resize an existing payload to a new variant, preserving any cells
 * that still fit and dropping / padding as needed.
 */
export function resizeColumns(
  payload: ColumnsPayload,
  variant: ColumnsVariant,
): ColumnsPayload {
  const wanted = cellCountForVariant(variant)
  const cells: ColumnsCell[] = Array.from({ length: wanted }, (_, i) => ({
    content: payload.cells[i]?.content ?? '',
  }))
  return { layout: { kind: 'columns', variant }, cells }
}
