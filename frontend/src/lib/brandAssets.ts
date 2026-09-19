/**
 * Fresh Collective brand assets — client types and presentation rules.
 *
 * The backend owns the role vocabulary, the approved defaults and the
 * validation. This module owns only how a role is *shown* to an
 * administrator: what the source badge says, and what colour to put
 * behind a preview.
 *
 * The preview background is not decoration. Three of these assets are
 * a white dragonfly on a transparent canvas, and on a white card they
 * are invisible — which is precisely the confusion that made the wrong
 * mark survive this long. Each role therefore declares the surface it
 * is meant to be seen on, and the preview honours it.
 */

export type BrandAssetSource = 'custom' | 'default' | 'missing'

export interface BrandAsset {
  role: string
  title: string
  group: string
  intended_use: string
  recommended: string
  accepted_formats: string[]
  source: BrandAssetSource
  image_url: string | null
  public_url: string | null
  missing_note: string | null
  updated_at: string | null
  updated_by: string | null
  can_reset: boolean
}

export interface BrandAssetGroup {
  group: string
  label: string
  description: string
  assets: BrandAsset[]
}

/** What the badge beside each role says. */
export function sourceLabel(source: BrandAssetSource): string {
  if (source === 'custom') return 'Custom upload'
  if (source === 'default') return 'Approved default'
  return 'Missing'
}

export function sourceTone(source: BrandAssetSource): 'teal' | 'neutral' | 'amber' {
  if (source === 'custom') return 'teal'
  if (source === 'default') return 'neutral'
  return 'amber'
}

/**
 * The surface a role's artwork is designed to sit on. A logo drawn in
 * white must be previewed on navy or it reads as an empty box.
 */
export type PreviewSurface = 'light' | 'dark' | 'own'

const PREVIEW_SURFACE: Record<string, PreviewSurface> = {
  primary_light_logo: 'light',
  alternate_light_logo: 'light',
  // Carries its own teal panel — neither a light nor a dark card
  // should be visible behind it.
  logo_on_teal: 'own',
  logo_on_navy: 'dark',
  marketing_hero_logo: 'dark',
  compact_light_mark: 'light',
  compact_dark_mark: 'dark',
  favicon_app_icon: 'own',
  social_share_image: 'own',
}

export function previewSurface(role: string): PreviewSurface {
  return PREVIEW_SURFACE[role] ?? 'light'
}

/** Aspect box for the preview well. Square for everything except the
 *  social card, which is a landscape composition. */
export function previewAspect(role: string): string {
  return role === 'social_share_image' ? '1200 / 630' : '1 / 1'
}

/**
 * The accept attribute for the file input, derived from what the role
 * actually accepts rather than hard-coded — so a role that gains WebP
 * support on the backend gains it here with no second edit.
 */
export function acceptAttribute(formats: string[]): string {
  const mime: Record<string, string> = {
    PNG: 'image/png',
    WebP: 'image/webp',
    JPG: 'image/jpeg',
  }
  return formats.map((f) => mime[f]).filter(Boolean).join(',')
}

/** "Replaced by Lindsey · 20 September 2026", or null when the role is
 *  on its approved default (a file in the repo has no editor and no
 *  edit date, and inventing one would be a small lie). */
export function attributionLine(asset: BrandAsset): string | null {
  if (asset.source !== 'custom' || !asset.updated_at) return null
  const when = new Date(asset.updated_at).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'long', year: 'numeric',
  })
  return asset.updated_by
    ? `Replaced by ${asset.updated_by} · ${when}`
    : `Replaced ${when}`
}

/** Count of roles still awaiting approved artwork, for the summary
 *  line at the top of the page. */
export function missingCount(groups: BrandAssetGroup[]): number {
  return groups.reduce(
    (n, g) => n + g.assets.filter((a) => a.source === 'missing').length,
    0,
  )
}
