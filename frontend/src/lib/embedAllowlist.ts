/**
 * Embed allowlist + display metadata for `embed` content blocks.
 *
 * Mirrors `backend/app/services/embed_validator.py`. The backend is the
 * source of truth — it rejects unsafe URLs on save. This module exists
 * to (a) give the creator immediate inline feedback before submitting and
 * (b) pick sensible iframe display dimensions per provider.
 *
 * Storage model: only validated URLs are stored in `embed_url`, never
 * raw HTML. The renderer always builds a fresh <iframe> with sandbox
 * attributes — never injects creator-supplied markup.
 */

export type EmbedShape = 'video' | 'tall' | 'short'

/**
 * Two heights, for a provider that publishes different sizing for
 * phones and desktops rather than one number.
 *
 * `breakpoint` is typed as the literal `900` on purpose. A CSS media
 * query cannot read a custom property, so the width cannot be passed
 * through at render time — it has to exist as a real rule in
 * `globals.css`, and `.fc-embed-h-900` is the only one that does. The
 * literal type is what stops a future provider declaring a breakpoint
 * with no stylesheet behind it: adding `1200` here will not compile
 * until the matching rule exists.
 */
export interface EmbedResponsiveHeight {
  /** Viewport width (px) at which `wide` takes over from `narrow`. */
  breakpoint: 900
  /** Height (px) below the breakpoint. */
  narrow: number
  /** Height (px) at or above it. */
  wide: number
}

export interface EmbedProvider {
  /** Human label shown in helper text */
  name: string
  /** Hostnames that map to this provider (exact match) */
  hosts: readonly string[]
  /** Display shape — picks aspect ratio / height */
  shape: EmbedShape
  /** Min iframe height in px (only used when shape !== 'video') */
  minHeight?: number
  /**
   * Set only when one height genuinely does not fit. `minHeight` stays
   * the pre-breakpoint fallback, so a provider carrying both renders
   * correctly even before the media query applies.
   */
  responsiveHeight?: EmbedResponsiveHeight
}

export const EMBED_PROVIDERS: readonly EmbedProvider[] = [
  { name: 'YouTube',      hosts: ['youtube.com', 'www.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com', 'youtu.be'], shape: 'video' },
  { name: 'Vimeo',        hosts: ['vimeo.com', 'player.vimeo.com'], shape: 'video' },
  { name: 'Wistia',       hosts: ['wistia.com', 'fast.wistia.com', 'fast.wistia.net'], shape: 'video' },
  { name: 'Loom',         hosts: ['loom.com', 'www.loom.com'], shape: 'video' },
  { name: 'Google Forms', hosts: ['forms.gle', 'docs.google.com'], shape: 'tall', minHeight: 600 },
  { name: 'Typeform',     hosts: ['typeform.com', 'form.typeform.com'], shape: 'tall', minHeight: 600 },
  { name: 'Calendly',     hosts: ['calendly.com'], shape: 'tall', minHeight: 700 },
  { name: 'Spotify',      hosts: ['spotify.com', 'open.spotify.com'], shape: 'short', minHeight: 232 },
  { name: 'SoundCloud',   hosts: ['soundcloud.com', 'w.soundcloud.com'], shape: 'short', minHeight: 166 },
  // Neutrino Human Design charts. Only the exact widget path is
  // accepted — the backend pins it (see ``EMBED_ALLOWED_PATHS``)
  // because the same host also serves Neutrino's app and its loader
  // script, neither of which belongs in a chart block.
  //
  // Neutrino's own embed snippet ships a <script> + <neutrino-widget>
  // element and a <style> block. None of that is used: we keep the
  // iframe src, store the URL, and render it ourselves. The two heights
  // below are the ones that <style> block sets.
  {
    name: 'Neutrino Human Design',
    hosts: ['neutrinoplatform.com'],
    shape: 'tall',
    minHeight: 1500,
    responsiveHeight: { breakpoint: 900, narrow: 1500, wide: 850 },
  },
]

const ALL_HOSTS = new Set(EMBED_PROVIDERS.flatMap(p => p.hosts))

/**
 * If `raw` is an <iframe ...> snippet, extract its src attribute.
 * If `raw` is already a URL, return as-is.
 * Returns null if no usable URL can be extracted.
 */
export function extractEmbedSrc(raw: string): string | null {
  const s = (raw ?? '').trim()
  if (!s) return null

  if (s.toLowerCase().includes('<iframe')) {
    const m = s.match(/<iframe\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']/i)
    if (!m) return null
    return m[1].trim()
  }
  if (!/^https?:\/\//i.test(s)) return null
  return s
}

/**
 * Resolve the provider that matches a URL's hostname, or null if the
 * host is not on the allowlist.
 */
export function getEmbedProvider(url: string): EmbedProvider | null {
  let host: string
  try {
    host = new URL(url).hostname.toLowerCase()
  } catch {
    return null
  }
  if (!host) return null

  for (const p of EMBED_PROVIDERS) {
    if (p.hosts.includes(host)) return p
    if (p.hosts.some(h => host.endsWith('.' + h))) return p
  }
  return null
}

export type EmbedCheck =
  | { ok: true; url: string; provider: EmbedProvider }
  | { ok: false; reason: string }

/**
 * Validate raw user input (URL or iframe snippet) for use as an embed.
 * Returns the extracted URL and the matched provider on success, or a
 * human-readable reason on failure. Mirrors the backend validator.
 */
export function checkEmbed(raw: string): EmbedCheck {
  const src = extractEmbedSrc(raw)
  if (!src) {
    return {
      ok: false,
      reason: raw.toLowerCase().includes('<iframe')
        ? 'Could not find src= in the iframe code.'
        : 'Paste an https:// URL or the full <iframe ...> embed code.',
    }
  }

  let parsed: URL
  try {
    parsed = new URL(src)
  } catch {
    return { ok: false, reason: 'Not a valid URL.' }
  }
  if (parsed.protocol !== 'https:') {
    return { ok: false, reason: 'Embed URL must use https://.' }
  }

  const provider = getEmbedProvider(src)
  if (!provider) {
    const supported = EMBED_PROVIDERS.map(p => p.name).join(', ')
    return {
      ok: false,
      reason: `Host "${parsed.hostname}" is not allowed. Supported: ${supported}.`,
    }
  }

  return { ok: true, url: src, provider }
}

/**
 * How to size a non-video embed: the class and inline style its iframe
 * needs. Pure, so the height decision is assertable without rendering.
 *
 * A provider with one height keeps exactly the shape it had before —
 * `minHeight`/`height` and no class. One with two heights gets the
 * narrow height inline (correct below the breakpoint, and correct
 * before CSS applies at all) plus `.fc-embed-h-900`, which swaps in the
 * wide height from the custom property above 900px.
 */
export function resolveEmbedBox(provider: EmbedProvider): {
  className: string
  style: Record<string, string | number>
} {
  const fallback = provider.minHeight ?? (provider.shape === 'short' ? 200 : 600)
  const rh = provider.responsiveHeight
  if (!rh) {
    return { className: '', style: { minHeight: fallback, height: fallback } }
  }
  return {
    className: `fc-embed-h-${rh.breakpoint}`,
    style: {
      minHeight: rh.narrow,
      height: rh.narrow,
      '--fc-embed-h-wide': `${rh.wide}px`,
    },
  }
}

/** Human-readable list of supported providers, for helper text. */
export function supportedEmbedsList(): string {
  return EMBED_PROVIDERS.map(p => p.name).join(', ')
}

/** True if any of the allowed providers includes this host. */
export function isEmbedHostAllowed(host: string): boolean {
  const h = host.toLowerCase()
  if (ALL_HOSTS.has(h)) return true
  for (const allowed of ALL_HOSTS) {
    if (h.endsWith('.' + allowed)) return true
  }
  return false
}
