/**
 * Renders a CTA button block.
 *
 * Storage on ``pathway_step_blocks.caption`` for a button is one of:
 *
 *   1. Legacy: one of ``primary`` | ``secondary`` | ``outline`` |
 *      ``subtle`` — the four hard-coded styles from the pre-palette
 *      button era. Kept for backward compatibility: existing buttons
 *      render *exactly* as they used to (Fresh Collective teal/navy
 *      Tailwind classes) even after this refactor.
 *
 *   2. New: a JSON envelope combining the writer's picked *style*
 *      (Filled / Outline / Text only) with the picked *colour*
 *      (``palette:<role>`` for palette-linked, ``custom:#RRGGBB`` for
 *      an explicit hex override):
 *
 *          {"style":"filled","colour":"palette:primary"}
 *          {"style":"outline","colour":"custom:#3A6B7A"}
 *          {"style":"text","colour":"palette:accent"}
 *
 * ``parseButtonCaption`` decodes both. ``encodeButtonCaption`` is used
 * by the editor to write the new format. Legacy captions are never
 * rewritten silently — a button only switches to JSON when the writer
 * touches its Style or Colour in the editor.
 *
 * Backend validates that `href` is https://, http://, mailto: or
 * starts with /; this component just decides between <Link> (internal)
 * and <a> (external/mailto) and applies safe rel attributes.
 */

import Link from 'next/link'
import {
  parseStoredColour,
  paletteHex,
  type CollectivePaletteMeta,
} from '@/lib/collectivePalette'
import {
  parseButtonCaption,
  type ButtonNewStyle,
  type ButtonStyle,
  type ParsedButtonCaption,
} from '@/lib/buttonCaption'

// Re-export the codec + types so existing callers can keep importing
// from '@/components/ButtonBlock' unchanged. The codec itself lives
// in a server-safe module so member-page SSR can call it too.
export {
  defaultButtonCaption,
  encodeButtonCaption,
  parseButtonCaption,
} from '@/lib/buttonCaption'
export type { ButtonNewStyle, ButtonStyle, ParsedButtonCaption } from '@/lib/buttonCaption'


export const BUTTON_NEW_STYLES: { value: ButtonNewStyle; label: string; description: string }[] = [
  { value: 'filled',  label: 'Filled',  description: 'Solid background with white text' },
  { value: 'outline', label: 'Outline', description: 'Coloured border with a transparent fill' },
  { value: 'text',    label: 'Text',    description: 'No background — text-only link' },
]

// Kept for back-compat picker fallback; new callers use BUTTON_NEW_STYLES.
export const BUTTON_STYLES: { value: ButtonStyle; label: string }[] = [
  { value: 'primary',   label: 'Primary' },
  { value: 'secondary', label: 'Secondary' },
  { value: 'outline',   label: 'Outline' },
  { value: 'subtle',    label: 'Subtle' },
]


// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

const BASE_CLASSES =
  'inline-flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-[14px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 focus-visible:ring-offset-2'


/** Legacy Tailwind class strings. Unchanged so pre-migration buttons
 *  render byte-identically. */
function legacyClasses(style: ButtonStyle): string {
  switch (style) {
    case 'primary':
      return `${BASE_CLASSES} bg-teal-600 text-white hover:bg-teal-700`
    case 'secondary':
      return `${BASE_CLASSES} bg-navy-900 text-white hover:bg-navy-800`
    case 'outline':
      return `${BASE_CLASSES} border-2 border-teal-600 bg-transparent text-teal-700 hover:bg-teal-50`
    case 'subtle':
      return `${BASE_CLASSES} bg-slate-100 text-navy-900 hover:bg-slate-200`
  }
}


/** True if a resolved hex is dark enough that white text reads well
 *  on top. Uses the standard luminance heuristic. Kept local to
 *  avoid pulling a colour-math dep. */
function preferWhiteOn(hex: string): boolean {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return true
  const n = parseInt(m[1], 16)
  const r = (n >> 16) & 0xff
  const g = (n >> 8) & 0xff
  const b = n & 0xff
  // Relative luminance (sRGB weighting).
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
  return luminance < 0.6
}


/**
 * Build inline styles + className for a modern button caption. The
 * caller passes the resolved hex (already looked up against the
 * active collective palette, or extracted from ``custom:#hex``).
 * Style variants:
 *
 *   filled  — solid background, contrast-aware text
 *   outline — coloured 2px border, coloured text, transparent bg
 *   text    — no chrome, coloured text only
 */
function modernRender(style: ButtonNewStyle, hex: string): {
  className: string
  style: React.CSSProperties
} {
  const textOnFilled = preferWhiteOn(hex) ? '#FFFFFF' : '#0C1826'
  if (style === 'filled') {
    return {
      className: `${BASE_CLASSES} hover:opacity-90`,
      style: { background: hex, color: textOnFilled },
    }
  }
  if (style === 'outline') {
    return {
      className: `${BASE_CLASSES} bg-transparent hover:bg-black/[3%]`,
      style: { border: `2px solid ${hex}`, color: hex },
    }
  }
  // text
  return {
    className: `${BASE_CLASSES} bg-transparent px-3 hover:bg-black/[3%]`,
    style: { color: hex },
  }
}


interface ButtonBlockProps {
  href: string
  text: string
  /**
   * Legacy shortcut: a bare ButtonStyle. When both ``style`` and
   * ``caption`` are provided, ``style`` wins (so existing callers
   * that pass one of the four legacy styles keep working).
   */
  style?: ButtonStyle | null
  /**
   * Preferred: the raw stored caption. Handles both legacy and the
   * new ``{style, colour}`` JSON envelope internally.
   */
  caption?: string | null
  /** The collective's active palette, for resolving ``palette:<role>``
   *  colours. Falls back to the legacy Fresh Collective teal on
   *  ``palette:primary`` when no palette is provided. */
  collectivePalette?: CollectivePaletteMeta | null
  /** "new_tab", "same_tab", or null (auto: external → new tab). */
  newTabPref?: 'new_tab' | 'same_tab' | null
  /** True for editor preview — no navigation. */
  previewOnly?: boolean
}


export default function ButtonBlock({
  href,
  text,
  style,
  caption,
  collectivePalette,
  newTabPref,
  previewOnly = false,
}: ButtonBlockProps) {
  // Prefer the explicit legacy style prop (existing callers); fall
  // back to parsing the raw caption.
  const parsed: ParsedButtonCaption = style
    ? { kind: 'legacy', style }
    : parseButtonCaption(caption)

  // ``previewOnly`` means "do not navigate" — it does NOT mean
  // "render a disabled/greyed-out button". The style previews in the
  // editor must look identical to what the published button will look
  // like so the writer can decide between Filled / Outline / Text at
  // a glance. Genuine disabled-button styling (grey background, muted
  // text) is unused today; if we ever need it, expose a separate
  // ``disabled`` prop rather than reusing ``previewOnly``.
  let className: string
  let inlineStyle: React.CSSProperties | undefined
  if (parsed.kind === 'legacy') {
    className = legacyClasses(parsed.style)
    inlineStyle = undefined
  } else {
    // Resolve the colour value — palette role, custom hex, or fallback.
    const colourParsed = parseStoredColour(parsed.colour)
    let hex = '#38A09E' // graceful fallback to Fresh Collective teal
    if (colourParsed.kind === 'palette') {
      hex = paletteHex(colourParsed.role, collectivePalette) ?? hex
    } else if (colourParsed.kind === 'custom') {
      hex = colourParsed.hex
    }
    const rendered = modernRender(parsed.style, hex)
    className = rendered.className
    inlineStyle = rendered.style
  }

  const label = text || 'Button'

  if (previewOnly) {
    return (
      <span className={className} style={inlineStyle} aria-disabled="true">
        {label}
      </span>
    )
  }

  const newTab =
    newTabPref === 'new_tab' ? true :
    newTabPref === 'same_tab' ? false :
    defaultNewTab(href)

  // Internal app links: use Next.js client navigation.
  if (isInternalHref(href) && !newTab) {
    return (
      <Link href={href} className={className} style={inlineStyle}>
        {label}
      </Link>
    )
  }

  // mailto: always opens in user's email client — same tab is expected.
  if (isMailtoHref(href)) {
    return (
      <a href={href} className={className} style={inlineStyle}>
        {label}
      </a>
    )
  }

  // External (or internal-but-forced-new-tab): plain <a> with safe rel.
  return (
    <a
      href={href}
      className={className}
      style={inlineStyle}
      target={newTab ? '_blank' : undefined}
      rel={newTab ? 'noopener noreferrer' : undefined}
    >
      {label}
      {newTab && <span aria-hidden className="text-[11px] opacity-70">↗</span>}
    </a>
  )
}


// ---------------------------------------------------------------------------
// Href helpers (public API — unchanged)
// ---------------------------------------------------------------------------

/** True if the URL is an internal app path (starts with /) — uses Next <Link>. */
export function isInternalHref(href: string): boolean {
  return href.startsWith('/') && !href.startsWith('//')
}

/** True if the URL is a mailto: link. */
export function isMailtoHref(href: string): boolean {
  return href.toLowerCase().startsWith('mailto:')
}

/**
 * Decide the default open-in-new-tab behaviour when the creator hasn't
 * picked one: external URLs → new tab, internal/mailto → same tab.
 */
export function defaultNewTab(href: string): boolean {
  return !isInternalHref(href) && !isMailtoHref(href)
}

/**
 * Mirrors the backend validator. Returns null on success, error string on
 * rejection. Used by the editor for inline UX feedback before save.
 */
export function checkButtonUrl(raw: string): string | null {
  const s = (raw ?? '').trim()
  if (!s) return 'URL is required.'
  if (s.startsWith('//')) return 'Protocol-relative URLs are not allowed.'
  if (s.startsWith('/')) return null
  const lower = s.toLowerCase()
  if (lower.startsWith('mailto:')) {
    const addr = s.slice('mailto:'.length).trim()
    if (!addr || !addr.includes('@')) return 'mailto: link must include an email address.'
    return null
  }
  if (!lower.startsWith('http://') && !lower.startsWith('https://')) {
    return 'URL must start with https://, http://, mailto:, or / for internal links.'
  }
  try {
    const u = new URL(s)
    if (!u.hostname) return 'URL is missing a hostname.'
  } catch {
    return 'Not a valid URL.'
  }
  return null
}
