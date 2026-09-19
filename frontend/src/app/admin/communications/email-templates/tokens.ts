/**
 * Surface tokens for the Email Templates pages.
 *
 * Deliberately the same warm, quiet surface as the rest of World
 * Management — see `src/lib/wm-palette.ts` for the accent hierarchy.
 * Nothing new is invented here; these are named so the three files of
 * this feature stay consistent with each other.
 */

export const PAGE_BG = '#FBFDFC'
export const CARD_BG = '#FFFFFF'
export const CARD_BORDER = '1px solid #E7EEF0'
export const CARD_SHADOW =
  '0 2px 10px rgba(16, 24, 40, 0.04), 0 1px 2px rgba(16, 24, 40, 0.03)'
export const INK = '#0C1826'
export const INK_MUTED = 'rgba(12, 24, 38, 0.60)'
export const INK_SOFTER = 'rgba(12, 24, 38, 0.42)'
export const HAIRLINE = '1px solid rgba(12, 24, 38, 0.07)'
export const FIELD_BORDER = '1px solid rgba(12, 24, 38, 0.14)'

export const SERIF_ITALIC: React.CSSProperties = {
  color: INK_MUTED,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}

export interface Hue {
  bg: string
  border: string
  text: string
}

export const NEUTRAL: Hue = {
  bg: 'rgba(12, 24, 38, 0.04)',
  border: 'rgba(12, 24, 38, 0.12)',
  text: INK_MUTED,
}
export const TEAL: Hue = {
  bg: 'rgba(56, 160, 158, 0.10)',
  border: 'rgba(56, 160, 158, 0.30)',
  text: '#0f766e',
}
export const NAVY: Hue = {
  bg: 'rgba(56, 116, 180, 0.10)',
  border: 'rgba(56, 116, 180, 0.30)',
  text: '#1e40af',
}
export const GOLD: Hue = {
  bg: 'rgba(212, 176, 72, 0.12)',
  border: 'rgba(212, 176, 72, 0.32)',
  text: '#8A6A15',
}
export const CORAL: Hue = {
  bg: 'rgba(214, 96, 87, 0.08)',
  border: 'rgba(214, 96, 87, 0.28)',
  text: '#a63c30',
}
