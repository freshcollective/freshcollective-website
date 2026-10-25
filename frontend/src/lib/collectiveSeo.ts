/**
 * SEO metadata for a Collective, built from what its creator already wrote.
 *
 * No new creator-facing fields: the title comes from the name, the
 * description from the tagline or the description, and the social image
 * from the Location the creator chose. A creator who fills in their
 * Collective gets working metadata without being asked a second set of
 * questions about it.
 *
 * Privacy is NOT enforced here, and that is deliberate. Metadata is
 * built from whatever ``GET /api/spaces/{slug}`` returned, and that
 * endpoint already refuses an anonymous caller for a non-public
 * Collective (401) and a non-manager for a non-active one (404). Search
 * engine and social crawlers are anonymous, so there is nothing for
 * them to read before these functions are reached. The caller still
 * passes ``isPublic`` so a restricted page can be marked ``noindex`` —
 * belt to that architecture's braces, not a substitute for it.
 */

// Relative with the extension, matching the other node-tested libs:
// the '@/' alias is a tsconfig path the bare test runner cannot
// resolve, so an aliased import here breaks collectiveSeo.test.ts.
import { BUNDLED_DEFAULTS } from './brand.ts'

/**
 * The canonical origin.
 *
 * A constant rather than an env var: ``PUBLIC_APP_URL`` is set on
 * fc-api but not on fc-web, and adding one would mean a Dashboard entry
 * to keep in step for a value that changes about once per domain
 * migration. ``metadataBase`` needs it to turn relative canonical and
 * image paths into the absolute URLs crawlers require.
 */
export const SITE_ORIGIN = 'https://freshcollective.au'

/**
 * The fallback social image.
 *
 * An approved brand asset that already ships in ``public/``. It is
 * 500×500, so a card renders it square rather than in the 1.91:1 most
 * platforms prefer — acceptable for a fallback, and worth replacing
 * with a purpose-made 1200×630 image if social previews become a
 * priority. Chosen over ``home/hero-community.webp`` because WebP
 * support across social crawlers is still uneven where PNG is not.
 *
 * Read from ``lib/brand.ts`` rather than restated here.
 * ``test_brand_phase_b`` requires that module to be the only place in
 * the frontend naming a brand asset path — one logo change should not
 * be a multi-file change — and spelling the path again here broke it.
 * ``BUNDLED_DEFAULTS`` is typed ``string | null`` across all roles, so
 * this reads through a narrowing assertion rather than a ``??``
 * fallback. There is no honest fallback to name: brand.ts is explicit
 * that a caller may never invent a substitute asset, and the earlier
 * ``?? '/brand/fallback.png'`` named a file that does not exist. The
 * value is non-null in the table and a contract test
 * (``test_every_frontend_default_exists_on_disk``) keeps it that way.
 */
export const DEFAULT_SOCIAL_IMAGE =
  BUNDLED_DEFAULTS.primary_light_logo as string

/** Meta descriptions are truncated to this. */
const MAX_DESCRIPTION = 155

export interface CollectiveSeoInput {
  name: string
  tagline?: string | null
  description?: string | null
  isPublic?: boolean
  location?: { hero_artwork_url?: string | null } | null
}

/**
 * Strip markup and normalise whitespace.
 *
 * ``description`` is plain text by convention but not by constraint,
 * and nothing stops a creator pasting markup into it. Tags are removed
 * rather than escaped — an escaped tag in a meta description is worse
 * than no tag, because it renders as literal angle brackets in a search
 * result.
 */
export function cleanText(value: string | null | undefined): string {
  if (!value) return ''
  return value
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * Truncate on a word boundary, with an ellipsis.
 *
 * Cutting mid-word reads as a fault rather than as a summary, so the
 * break moves back to the last space. A single word longer than the
 * limit is cut hard, because there is no boundary to find.
 */
export function truncate(value: string, max = MAX_DESCRIPTION): string {
  if (value.length <= max) return value
  const slice = value.slice(0, max - 1)
  const lastSpace = slice.lastIndexOf(' ')
  const body = lastSpace > max * 0.5 ? slice.slice(0, lastSpace) : slice
  return `${body.replace(/[.,;:—-]+$/, '')}…`
}

/** ``EMBODY · Fresh Collective`` — the separator the platform already uses. */
export function collectiveTitle(name: string): string {
  const clean = cleanText(name)
  return clean ? `${clean} · Fresh Collective` : 'Fresh Collective'
}

/**
 * The description ladder.
 *
 *   1. tagline  → "{tagline} Discover {name} on Fresh Collective."
 *   2. description → the creator's own words, trimmed
 *   3. neither  → a generic line in Fresh Collective's current voice
 *
 * A tagline is the better summary when it exists: it is short by
 * nature, so it survives truncation intact and leaves room to name the
 * Collective. A description is usually a paragraph, so rung 2 uses it
 * alone rather than appending a sentence that would be cut off.
 */
export function collectiveDescription(input: CollectiveSeoInput): string {
  const name = cleanText(input.name) || 'this Collective'
  const tagline = cleanText(input.tagline)
  if (tagline) {
    const lead = /[.!?]$/.test(tagline) ? tagline : `${tagline}.`
    return truncate(`${lead} Discover ${name} on Fresh Collective.`)
  }
  const description = cleanText(input.description)
  if (description) return truncate(description)
  return truncate(
    `Discover ${name} on Fresh Collective — a home for creator-led communities.`,
  )
}

/**
 * The social image: the Collective's Location artwork, else the brand.
 *
 * Deliberately NOT ``cover_image_url``. Covers are served from
 * ``/api/uploads/covers/…``, which requires a session — an anonymous
 * request returns 401, so a social crawler would fetch nothing and the
 * card would render imageless. The creator who shared the link would
 * see it working, because they are signed in. Location artwork lives
 * under ``/api/uploads/platform-artwork/…``, which is public, and under
 * the Atlas it IS the Collective's visual identity.
 */
export function collectiveSocialImage(input: CollectiveSeoInput): string {
  const hero = input.location?.hero_artwork_url
  return hero && hero.startsWith('/api/uploads/platform-artwork/')
    ? hero
    : DEFAULT_SOCIAL_IMAGE
}

/**
 * Everything the page's ``generateMetadata`` needs, in one call.
 *
 * ``canonical`` points at ``/about`` because that is where a visitor
 * lands: ``/spaces/[slug]`` redirects non-members there, so without
 * this the two URLs look like duplicates of each other.
 */
export function collectiveMetadata(input: CollectiveSeoInput, slug: string) {
  const title = collectiveTitle(input.name)
  const description = collectiveDescription(input)
  const image = collectiveSocialImage(input)
  const canonical = `/spaces/${slug}/about`
  // Only a public Collective is indexable. A restricted one is already
  // unreachable anonymously, so this cannot be the only guard — but a
  // signed-in member's page should not invite indexing either.
  const indexable = input.isPublic !== false

  return {
    title,
    description,
    alternates: { canonical },
    robots: indexable ? undefined : { index: false, follow: false },
    openGraph: {
      title,
      description,
      url: canonical,
      type: 'website' as const,
      images: [{ url: image }],
    },
    twitter: {
      card: 'summary_large_image' as const,
      title,
      description,
      images: [image],
    },
  }
}
