/**
 * Server-safe codec for the ``button`` block's ``caption`` column.
 *
 * Two on-disk encodings coexist:
 *
 *   1. Legacy — a bare string, one of ``primary`` | ``secondary`` |
 *      ``outline`` | ``subtle``. These are the four hard-coded
 *      pre-palette styles. Rendered byte-identically by ButtonBlock
 *      so existing content never shifts.
 *
 *   2. Modern — a JSON envelope combining a picked *style*
 *      (Filled / Outline / Text) with a picked *colour* (a
 *      palette-linked role or an explicit ``custom:#RRGGBB`` override):
 *
 *          {"style":"filled","colour":"palette:primary"}
 *
 * This module lives outside the React tree so both Server Components
 * (member step + About pages) and the client-side ButtonBlock share
 * one canonical parse. No inline JSON.parse elsewhere.
 */


/** Legacy caption values kept in ``caption``. Do not rename or drop. */
export type ButtonStyle = 'primary' | 'secondary' | 'outline' | 'subtle'

/** Editor-facing modern styles paired with any colour. */
export type ButtonNewStyle = 'filled' | 'outline' | 'text'


export type ParsedButtonCaption =
  | { kind: 'legacy'; style: ButtonStyle }
  | { kind: 'modern'; style: ButtonNewStyle; colour: string }


const LEGACY_STYLES: ReadonlySet<string> = new Set(['primary', 'secondary', 'outline', 'subtle'])
const NEW_STYLES:    ReadonlySet<string> = new Set(['filled', 'outline', 'text'])


/** Default caption for a brand-new button block. */
export function defaultButtonCaption(): string {
  return encodeButtonCaption('filled', 'palette:primary')
}


export function encodeButtonCaption(style: ButtonNewStyle, colour: string): string {
  return JSON.stringify({ style, colour })
}


export function parseButtonCaption(caption: string | null | undefined): ParsedButtonCaption {
  if (!caption) return { kind: 'legacy', style: 'primary' }
  const trimmed = caption.trim()
  if (LEGACY_STYLES.has(trimmed)) {
    return { kind: 'legacy', style: trimmed as ButtonStyle }
  }
  if (trimmed.startsWith('{')) {
    try {
      const parsed = JSON.parse(trimmed) as { style?: string; colour?: string }
      const style = parsed?.style && NEW_STYLES.has(parsed.style) ? parsed.style as ButtonNewStyle : 'filled'
      const colour = typeof parsed?.colour === 'string' ? parsed.colour : 'palette:primary'
      return { kind: 'modern', style, colour }
    } catch {
      // fall through
    }
  }
  return { kind: 'legacy', style: 'primary' }
}
