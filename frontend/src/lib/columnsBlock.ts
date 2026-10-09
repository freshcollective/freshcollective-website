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
 *       { "kind": "image", "content": "",
 *         "image": { "assetId": "…", "url": "/uploads/…",
 *                    "alt": null, "caption": null } }
 *     ]
 *   }
 *
 * The envelope is deliberately split into ``layout`` and ``cells`` so
 * future layout kinds (cards, comparison table, 4-column grid) can
 * reuse the same shape with a different ``layout.kind`` / ``variant``.
 * Callers that only understand today's ``columns`` kind should fall
 * back to a generic side-by-side render when they encounter an
 * unfamiliar variant, so old rows never break.
 *
 * Three properties of this module are load-bearing elsewhere, and the
 * tests in ``columnsBlock.test.ts`` exist to keep them true:
 *
 * 1. **An absent ``kind`` means text.** Every columns block written
 *    before image support had cells of the shape ``{ content }``, so a
 *    legacy row must decode — and re-encode — unchanged. Nothing has to
 *    be migrated, converted or republished.
 *
 * 2. **Decoding preserves what it does not render.** ``content`` is
 *    kept on image cells and ``image`` on text cells, so switching a
 *    column's type is reversible rather than destructive. Only the
 *    selected type is rendered; the other is carried quietly.
 *
 * 3. **Cells beyond the variant's column count are parked, not
 *    dropped.** Narrowing four columns to two used to discard the last
 *    two cells the moment the creator clicked the layout picker. They
 *    are now kept in ``cells`` and come back if the creator widens
 *    again. ``activeCells`` is what renderers iterate — never
 *    ``payload.cells`` directly, or a parked column would reappear on
 *    the member's page.
 *
 * ``content`` is a passthrough text column: no part of the API joins
 * ``creator_media_assets`` for anything stored inside it. An image cell
 * therefore carries its own resolved ``url``, because an ``assetId``
 * alone would paint an empty column. ``assetId`` is kept alongside it
 * as provenance — it is how the media usage endpoint finds images used
 * inside columns, and how a future repair pass could re-resolve a URL.
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

/** What a single column holds. Absent on legacy cells, meaning text. */
export type ColumnsCellKind = 'text' | 'image'

export const COLUMNS_CELL_KINDS: ColumnsCellKind[] = ['text', 'image']

export interface ColumnsCellImage {
  /** The media library asset this came from, where it came from one.
   *  ``null`` for an external ``embed_url``-style image. */
  assetId: string | null
  /** Resolved file URL — what the renderers actually use. */
  url: string
  /** Three states, matching image blocks exactly: ``null`` inherits the
   *  asset title, ``''`` marks the image decorative, and a non-empty
   *  string is explicit alt text. */
  alt?: string | null
  /** The asset's title at the time it was chosen, so the ``alt === null``
   *  inherit state can still resolve. Image blocks read this off the
   *  hydrated ``media_asset``; nothing hydrates ``content``, so a cell
   *  has to carry it. Resolve through ``cellImageAlt``, never by hand. */
  assetTitle?: string | null
  caption?: string | null
}

export interface ColumnsCell {
  content: string
  kind?: ColumnsCellKind
  image?: ColumnsCellImage
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


/** Widest variant, and so the most cells any payload can hold. Parked
 *  cells are previously-active cells, so they can never push a payload
 *  past this; the cap only bounds malformed input. */
export const MAX_COLUMNS_CELLS: number = COLUMNS_VARIANTS.reduce(
  (most, v) => Math.max(most, cellCountForVariant(v)),
  0,
)


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


/** Empty envelope for freshly-inserted columns blocks. Every column
 *  starts as text, so a new block opens on the familiar rich text
 *  editors rather than asking the creator to choose anything. */
export function emptyColumnsPayload(variant: ColumnsVariant = '50-50'): ColumnsPayload {
  const n = cellCountForVariant(variant)
  return {
    layout: { kind: 'columns', variant },
    cells: Array.from({ length: n }, () => ({ content: '' })),
  }
}


/**
 * Which type a cell is showing.
 *
 * Intent, not contents: a cell the creator switched to Image but has
 * not yet chosen a picture for still reports ``'image'``, so the editor
 * keeps showing the image controls across a reload. Renderers must
 * therefore check ``cell.image?.url`` before painting anything — an
 * image cell with no image renders nothing, exactly as an empty text
 * cell does today.
 */
export function cellKind(cell: ColumnsCell | undefined): ColumnsCellKind {
  return cell?.kind === 'image' ? 'image' : 'text'
}


/**
 * Alt text for a column's image.
 *
 * Mirrors the image block's ``block.label ?? block.media_asset?.title
 * ?? ''`` exactly, including the reason it uses ``??`` rather than
 * ``||``: an empty string is a creator's deliberate "this image is
 * decorative", and ``||`` would overwrite that with the asset title,
 * announcing a picture the creator asked screen readers to skip.
 *
 * Lives here rather than in each renderer so the member page, the
 * public About page and the Creator Studio preview cannot drift apart.
 */
export function cellImageAlt(image: ColumnsCellImage | undefined | null): string {
  if (!image) return ''
  return image.alt ?? image.assetTitle ?? ''
}


/** The cells this variant actually shows. Renderers iterate this, never
 *  ``payload.cells``, which may carry parked columns. */
export function activeCells(payload: ColumnsPayload): ColumnsCell[] {
  return payload.cells.slice(0, cellCountForVariant(payload.layout.variant))
}


/** Cells being held beyond the current variant's column count. */
export function parkedCells(payload: ColumnsPayload): ColumnsCell[] {
  return payload.cells.slice(cellCountForVariant(payload.layout.variant))
}


/** Whether a cell holds anything a member would see. Used to tell a
 *  creator that narrowing the layout has parked real content, rather
 *  than letting it vanish without a word. */
export function cellIsPopulated(cell: ColumnsCell | undefined): boolean {
  if (!cell) return false
  if (cell.image?.url?.trim()) return true
  return richTextHasContent(cell.content)
}


/** An empty TipTap editor serialises to ``''`` or ``<p></p>``, so a
 *  bare length check reads empty paragraphs as content. */
function richTextHasContent(html: string | null | undefined): boolean {
  if (!html) return false
  if (/<(img|iframe|video|hr)[\s>/]/i.test(html)) return true
  return html.replace(/<[^>]*>/g, '').replace(/&nbsp;/gi, ' ').trim().length > 0
}


function decodeCellImage(raw: unknown): ColumnsCellImage | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const src = raw as Partial<ColumnsCellImage>
  const url = typeof src.url === 'string' ? src.url.trim() : ''
  // No URL means nothing to render, so there is no image here. The
  // cell may still be of kind ``image``; the editor will show its
  // controls with nothing selected.
  if (!url) return undefined
  return {
    assetId:
      typeof src.assetId === 'string' && src.assetId.trim() ? src.assetId : null,
    url,
    // ``''`` survives — it is how a creator marks an image decorative.
    // Absent, null and anything non-string all mean "inherit the asset
    // title", normalised to null so there is one representation.
    alt: typeof src.alt === 'string' ? src.alt : null,
    assetTitle:
      typeof src.assetTitle === 'string' && src.assetTitle.trim()
        ? src.assetTitle
        : null,
    caption:
      typeof src.caption === 'string' && src.caption.trim() ? src.caption : null,
  }
}


function decodeCell(raw: unknown): ColumnsCell {
  const src = (raw && typeof raw === 'object' ? raw : {}) as Partial<ColumnsCell>
  const cell: ColumnsCell = {
    content: typeof src.content === 'string' ? src.content : '',
  }
  // Key order matters only in that it should be stable: the editor's
  // mutators build cells as content/kind/image, so decoding to the same
  // order makes ``encode(decode(x))`` idempotent and keeps a reopened
  // block from looking modified the moment it loads.
  //
  // Only ``'image'`` is recorded. Text is the default, so omitting it
  // keeps a legacy ``{ content }`` cell byte-identical through a
  // decode/encode round trip. An unrecognised kind falls back to text.
  if (src.kind === 'image') cell.kind = 'image'
  const image = decodeCellImage(src.image)
  if (image) cell.image = image
  return cell
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
      // Pad up to the variant's count, and keep anything past it: those
      // are columns a creator parked by narrowing the layout, and they
      // must still be there if the layout widens again.
      const length = Math.min(MAX_COLUMNS_CELLS, Math.max(wanted, raw.length))
      const cells: ColumnsCell[] = Array.from({ length }, (_, i) => decodeCell(raw[i]))
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
 * Resize an existing payload to a new variant, preserving cells by
 * position and padding with empty text cells as needed.
 *
 * Narrowing does not discard: the cells beyond the new column count are
 * parked (see the module note) so that choosing a narrower layout is
 * never the thing that loses a creator's writing.
 */
export function resizeColumns(
  payload: ColumnsPayload,
  variant: ColumnsVariant,
): ColumnsPayload {
  const wanted = cellCountForVariant(variant)
  const length = Math.min(
    MAX_COLUMNS_CELLS,
    Math.max(wanted, payload.cells.length),
  )
  const cells: ColumnsCell[] = Array.from(
    { length },
    (_, i) => payload.cells[i] ?? { content: '' },
  )
  return { layout: { kind: 'columns', variant }, cells }
}


/** Replace one cell, leaving the rest of the payload alone. */
function withCell(
  payload: ColumnsPayload,
  index: number,
  next: (cell: ColumnsCell) => ColumnsCell,
): ColumnsPayload {
  if (index < 0 || index >= payload.cells.length) return payload
  return {
    ...payload,
    cells: payload.cells.map((cell, i) => (i === index ? next(cell) : cell)),
  }
}


/** Switch a column between text and image.
 *
 * Both forms are kept. A creator who writes a paragraph, switches to
 * Image, then switches back finds their paragraph; the reverse keeps
 * the chosen image. Nothing is erased, so nothing needs confirming. */
export function setCellKind(
  payload: ColumnsPayload,
  index: number,
  kind: ColumnsCellKind,
): ColumnsPayload {
  return withCell(payload, index, (cell) => {
    const next: ColumnsCell = { ...cell }
    if (kind === 'image') next.kind = 'image'
    else delete next.kind
    return next
  })
}


/** Set a text column's rich text, leaving any parked image alone. */
export function setCellContent(
  payload: ColumnsPayload,
  index: number,
  content: string,
): ColumnsPayload {
  return withCell(payload, index, (cell) => ({ ...cell, content }))
}


/** Choose, replace or clear a column's image, leaving any parked text
 *  alone. Passing ``null`` removes the image but keeps the column in
 *  image mode, matching how removing an image block's picture behaves. */
export function setCellImage(
  payload: ColumnsPayload,
  index: number,
  image: ColumnsCellImage | null,
): ColumnsPayload {
  return withCell(payload, index, (cell) => {
    const next: ColumnsCell = { ...cell }
    if (image && image.url.trim()) next.image = image
    else delete next.image
    return next
  })
}
