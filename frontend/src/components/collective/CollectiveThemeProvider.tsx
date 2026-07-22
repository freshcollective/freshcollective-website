/**
 * CollectiveThemeProvider
 *
 * Wraps a collective-facing route tree in a scope that emits four CSS
 * custom properties keyed to the collective's Colour Palette:
 *
 *   --fc-collective-primary
 *   --fc-collective-secondary
 *   --fc-collective-accent
 *   --fc-collective-background
 *
 * Descendants can consume these via `var()` — e.g. a collective-scoped
 * primary button reads `background: var(--fc-collective-primary, #38A09E)`
 * with the Fresh Collective teal as a graceful fallback when no palette
 * has been chosen.
 *
 * Deliberately restrained: this provider only sets the four semantic
 * variables. It does not restyle every screen. Screen-level adoption is
 * incremental — start with the collective header, primary CTA, and
 * subtle accent lines. Core layout and typography are never overridden
 * so accessibility and Fresh Collective identity are preserved.
 *
 * Server component friendly — sets the vars inline on a wrapping <div>
 * with no client-side state.
 */

import { CollectivePaletteContextProvider } from './CollectivePaletteContext'
import type { CollectivePaletteMeta } from '@/lib/collectivePalette'

interface Palette {
  primary: string
  secondary: string
  accent: string
  background: string
}

interface Props {
  /**
   * The full colour-palette metadata for the current collective (as
   * returned by the space detail endpoint under ``colour_palette``).
   * When ``null`` / ``undefined`` the CSS variables are omitted and
   * the palette context falls back to null — every consumer degrades
   * gracefully to the platform default.
   *
   * Legacy callers may still pass the bare palette object (four hex
   * slots, no ``key``/``name``) — we accept both shapes.
   */
  palette: Palette | CollectivePaletteMeta | null | undefined
  className?: string
  children: React.ReactNode
}

export default function CollectiveThemeProvider({ palette, className, children }: Props) {
  // Accept both the bare 4-slot palette (legacy callers) and the full
  // metadata dict from the API. Normalise for the CSS-var layer and
  // for the palette context; each layer picks the shape it needs.
  const rawPalette: Palette | null = palette
    ? ('palette' in (palette as CollectivePaletteMeta)
        ? (palette as CollectivePaletteMeta).palette
        : (palette as Palette))
    : null
  const paletteMeta: CollectivePaletteMeta | null = palette && 'palette' in (palette as CollectivePaletteMeta)
    ? (palette as CollectivePaletteMeta)
    : rawPalette
    ? { key: '', name: '', palette: rawPalette }
    : null
  // Palette-scoped CSS custom properties. Consumers read via var(...)
  // with the Fresh Collective teal as a fallback for un-themed collectives.
  //
  // Two families of variable are emitted:
  //   --fc-collective-{primary,secondary,accent,background}
  //     Literal palette values, kept stable for existing callers.
  //   --fc-accent, --fc-accent-strong, --fc-accent-soft, --fc-accent-line
  //     Convenience aliases for the accent surfaces callers actually touch
  //     (buttons, tabs, links, badges, focus/hover, small accent lines).
  //     `soft` and `line` are alpha-blended over the primary so a single
  //     hex from the palette drives every surface without extra math at
  //     each callsite.
  const style: React.CSSProperties = rawPalette
    ? ({
        '--fc-collective-primary':    rawPalette.primary,
        '--fc-collective-secondary':  rawPalette.secondary,
        '--fc-collective-accent':     rawPalette.accent,
        '--fc-collective-background': rawPalette.background,
        // Convenience aliases — primary is used as "the" accent because
        // it is the one that reads most confidently at button size.
        '--fc-accent':                rawPalette.primary,
        '--fc-accent-strong':         rawPalette.secondary,
        '--fc-accent-soft':           rgba(rawPalette.primary, 0.10),
        '--fc-accent-line':           rgba(rawPalette.primary, 0.22),
      } as React.CSSProperties)
    : {}

  return (
    <div className={className} style={style}>
      <CollectivePaletteContextProvider palette={paletteMeta}>
        {children}
      </CollectivePaletteContextProvider>
    </div>
  )
}

// Small helper — accepts a #RRGGBB and returns an rgba() with the alpha.
// Silently returns the source when it can't parse.
function rgba(hex: string, alpha: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return hex
  const n = parseInt(m[1], 16)
  const r = (n >> 16) & 0xff
  const g = (n >> 8) & 0xff
  const b = n & 0xff
  return `rgba(${r},${g},${b},${alpha})`
}
