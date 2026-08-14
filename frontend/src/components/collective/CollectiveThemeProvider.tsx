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
        // Extra roles added for the M1 refinement pass — every collective
        // member surface (CTAs, sidebar, calendar highlights, hovers) can
        // theme itself off of this small set without a palette prop or
        // per-callsite maths.
        //
        //   --fc-accent-hover: primary darkened ~12%. Use for :hover on
        //     primary CTA to preserve state feedback without pulling in
        //     another palette slot.
        //   --fc-accent-ring: primary at 32% alpha. Use for focus rings /
        //     ring-1 borders where --fc-accent-line reads too pale.
        //   --fc-accent-tint: primary at 6% alpha. A gentler soft than
        //     --fc-accent-soft, for whole-panel backgrounds where 10%
        //     reads as loud.
        //   --fc-accent-contrast: WCAG-picked contrast text ("#0f172a"
        //     or "#ffffff") for text placed *on* a solid primary swatch
        //     (button label, filled chip). Chosen server-side against
        //     the primary hex so darker palettes get white and lighter
        //     palettes get near-black.
        '--fc-accent-hover':          darken(rawPalette.primary, 0.12),
        '--fc-accent-ring':           rgba(rawPalette.primary, 0.32),
        '--fc-accent-tint':           rgba(rawPalette.primary, 0.06),
        '--fc-accent-contrast':       pickContrastText(rawPalette.primary),
        // ── Platform-token overrides ────────────────────────────────
        // The Fresh Collective design-token layer (styles/fc-tokens.css)
        // defines --fc-accent-500 / -400 / -700 / -50 / -gradient at
        // :root as hard-coded teal. Every platform primitive — Button,
        // Input, Modal, Tabs, Card, StatusBadge, Checkbox, Switch — reads
        // *those* tokens, not the --fc-accent* roles above. Without
        // overriding them here, a <Button variant="primary"> renders in
        // teal even on The Grove because it interpolates
        // var(--fc-accent-gradient) which the provider never touched.
        //
        // Overriding the same names inside this provider's scope
        // cascades one Collective-primary-driven palette through every
        // platform primitive automatically, no per-component change.
        // Semantic tokens (--fc-status-*, --fc-ink-*, --fc-surface-*)
        // are deliberately NOT overridden — an error message must stay
        // red on every Collective.
        //
        // ``--fc-accent-500`` is the raw primary. ``--fc-accent-400`` is
        // the secondary (used as the right stop of the primary gradient).
        // ``--fc-accent-700`` darkens the primary by 20% — matches the
        // deep tone the original teal-700 provided for tertiary button
        // labels. ``--fc-accent-50`` is a very-soft tint for hover/pale
        // backgrounds. ``--fc-accent-gradient`` uses primary → secondary
        // so the two-stop gradient reads as belonging to this palette.
        // Focus rings pick up the palette so text-input focus feels
        // native to the Collective.
        '--fc-accent-500':            rawPalette.primary,
        '--fc-accent-400':            rawPalette.secondary,
        '--fc-accent-700':            darken(rawPalette.primary, 0.20),
        '--fc-accent-50':             rgba(rawPalette.primary, 0.06),
        '--fc-accent-gradient':       `linear-gradient(135deg, ${rawPalette.primary} 0%, ${rawPalette.secondary} 100%)`,
        '--fc-focus-ring':            `0 0 0 2px ${rgba(rawPalette.primary, 0.40)}`,
        '--fc-focus-ring-input':      `0 0 0 3px ${rgba(rawPalette.primary, 0.25)}`,
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

// Multiplicative RGB darken. Mirrors ``darkenHex`` in
// ``@/lib/collectivePalette`` — inlined here so this file stays
// server-safe without a client-boundary import cycle.
function darken(hex: string, amount: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return hex
  const n = parseInt(m[1], 16)
  const clamped = Math.max(0, Math.min(1, amount))
  const factor = 1 - clamped
  const r = Math.round(((n >> 16) & 0xff) * factor)
  const g = Math.round(((n >> 8) & 0xff) * factor)
  const b = Math.round((n & 0xff) * factor)
  const h2 = (v: number) => v.toString(16).padStart(2, '0')
  return `#${h2(r)}${h2(g)}${h2(b)}`
}

// Luminance-threshold contrast picker — near-black on genuinely light
// primaries, pure white on dark/medium primaries. Mirrors the
// ``contrastText`` helper in ``@/lib/collectivePalette`` (see the
// docstring there for the calibration rationale — same threshold,
// same behaviour, kept in sync so ``--fc-accent-contrast`` and the
// page-level ``contrastText`` call always agree). Inlined here to
// keep this file free of a client-boundary import cycle.
function pickContrastText(hex: string): '#0f172a' | '#ffffff' {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return '#0f172a'
  const n = parseInt(m[1], 16)
  const chan = (c: number) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
  }
  const r = (n >> 16) & 0xff
  const g = (n >> 8) & 0xff
  const b = n & 0xff
  const L = 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)
  return L > 0.42 ? '#0f172a' : '#ffffff'
}
