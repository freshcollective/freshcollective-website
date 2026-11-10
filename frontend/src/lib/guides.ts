/**
 * Guides — the decisions that are easier to test than to look at.
 *
 * Everything in here is pure, so the rules that shape a Guide page can
 * be asserted directly rather than inferred from a rendered tree:
 * which byline a Guide gets, which heading anchors the "On this page"
 * box and the body agree on, whether the Starter Kit is offered at
 * all, and what the structured data says.
 *
 * Imported with a relative ``.ts`` path by ``guides.test.ts``, so this
 * module must not use the ``@/`` alias — the bare node test runner
 * cannot resolve a tsconfig path.
 */

import { safeHref } from './safeHref.ts'

// ---------------------------------------------------------------------------
// Categories
// ---------------------------------------------------------------------------

/**
 * Stored as slugs, displayed from here.
 *
 * The database holds ``starting`` and the page shows "Starting your
 * Collective", so renaming the label later is a copy change rather
 * than a data migration. The order is the order the filter pills
 * appear in.
 */
export const GUIDE_CATEGORIES = [
  { slug: 'starting', label: 'Starting your Collective' },
  { slug: 'growing', label: 'Growing your Collective' },
  { slug: 'tools', label: 'Tools and resources' },
] as const

export type GuideCategorySlug = (typeof GUIDE_CATEGORIES)[number]['slug']

export function categoryLabel(slug: string): string {
  return GUIDE_CATEGORIES.find((c) => c.slug === slug)?.label ?? slug
}

// ---------------------------------------------------------------------------
// Shapes, matching the public API
// ---------------------------------------------------------------------------

export interface GuideCard {
  slug: string
  title: string
  standfirst: string
  category: string
  hero_image_url: string | null
  hero_image_alt: string | null
  reading_time_minutes: number
  published_at: string | null
  featured: boolean
}

export interface GuideArticle {
  slug: string
  title: string
  standfirst: string
  body: string
  category: string
  hero_image_url: string | null
  hero_image_alt: string | null
  seo_title: string | null
  seo_description: string | null
  author_name: string
  reading_time_minutes: number
  published_at: string | null
  updated_at: string
  cta_heading: string | null
  cta_text: string | null
  cta_label: string | null
  cta_href: string | null
}

export interface GuideIndexPayload {
  guides: GuideCard[]
  starter_kit_url: string | null
}

export interface GuideArticlePayload {
  guide: GuideArticle
  related: GuideCard[]
  starter_kit_url: string | null
}

// ---------------------------------------------------------------------------
// Byline
// ---------------------------------------------------------------------------

/** The author whose name carries the house descriptor. */
export const HOUSE_AUTHOR = 'Linds'

/**
 * "By Linds, founder of Fresh Collective" — or just "By Jo Smith".
 *
 * The descriptor belongs to one person, so it is attached to that one
 * name rather than stored per Guide. A guest author gets a plain
 * byline instead of a field that would quietly claim they founded the
 * place, and nobody has to remember to clear anything.
 */
export function bylineFor(authorName: string): string {
  const name = (authorName ?? '').trim() || HOUSE_AUTHOR
  return name === HOUSE_AUTHOR
    ? `By ${HOUSE_AUTHOR}, founder of Fresh Collective`
    : `By ${name}`
}

/** The single letter in the byline's avatar circle. */
export function authorInitial(authorName: string): string {
  const name = (authorName ?? '').trim() || HOUSE_AUTHOR
  return name.charAt(0).toUpperCase()
}

// ---------------------------------------------------------------------------
// Reading time and dates
// ---------------------------------------------------------------------------

export function readingTimeLabel(minutes: number): string {
  const n = Number.isFinite(minutes) && minutes > 0 ? Math.round(minutes) : 1
  return `${n} min read`
}

/**
 * "9 November 2026".
 *
 * ``en-AU`` with an explicit UTC time zone: the backend stores naive
 * UTC, and letting the server's locale decide would date a Guide
 * differently depending on which machine rendered it.
 */
export function formatGuideDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const value = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  if (Number.isNaN(value.getTime())) return ''
  return new Intl.DateTimeFormat('en-AU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(value)
}

// ---------------------------------------------------------------------------
// The Starter Kit
// ---------------------------------------------------------------------------

/**
 * Should the Creator Starter Kit be offered at all?
 *
 * One answer for both placements — the band at the foot of ``/guides``
 * and the card in a Guide's side column — so they can never disagree
 * about whether the kit exists.
 *
 * Empty is the shipped state and means *render nothing*: no band, no
 * card, no placeholder and no "coming soon". The backend validates
 * this value on write; this is the second check, because a page that
 * renders a button must know the button goes somewhere.
 */
export function starterKitHref(raw: string | null | undefined): string | null {
  return safeHref(raw)
}

export function showStarterKit(raw: string | null | undefined): boolean {
  return starterKitHref(raw) !== null
}

// ---------------------------------------------------------------------------
// Heading anchors
// ---------------------------------------------------------------------------

/**
 * The id for a heading, derived from its text.
 *
 * Derived rather than stored so the body and the "On this page" box
 * cannot disagree: both call this, so a link always points at a
 * heading that exists. Prefixed because a heading called "main" would
 * otherwise collide with the page's own landmarks.
 */
export function headingAnchor(text: string, index: number): string {
  const base = (text ?? '')
    .toLowerCase()
    .replace(/<[^>]*>/g, '')
    .replace(/&[a-z]+;/g, ' ')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  // The index is the fallback for a heading with no usable text — an
  // em dash, an emoji, a stray number. Collisions between two
  // real-worded headings are resolved by ``extractHeadings``, which
  // can see the whole document and this function cannot.
  return base ? `guide-${base}` : `guide-section-${index + 1}`
}

/**
 * The H2s in a body, in order, with a unique id each.
 *
 * Reads the stored HTML rather than a separate stored outline,
 * because a separate outline is a second thing to keep in step with
 * the article and it will eventually be wrong.
 *
 * **This is the only place ids are assigned.** ``GuideBody`` reads
 * the list this returns rather than deriving an id per heading as it
 * renders, so the "On this page" box and the headings it links to
 * cannot disagree — not even about a collision. Deriving them
 * separately looked identical and broke the moment a Guide used the
 * same wording twice: both headings took one id, and the second
 * entry in the contents scrolled to the first.
 */
export function extractHeadings(
  body: string,
): Array<{ id: string; text: string }> {
  const out: Array<{ id: string; text: string }> = []
  const used = new Map<string, number>()
  const re = /<h2[^>]*>([\s\S]*?)<\/h2>/gi
  let match: RegExpExecArray | null
  let index = 0
  while ((match = re.exec(body)) !== null) {
    const text = match[1]
      .replace(/<[^>]*>/g, '')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&nbsp;/g, ' ')
      .trim()
    if (text) {
      const base = headingAnchor(text, index)
      // Second and later uses get a suffix. The first keeps the clean
      // id, so an anchor already shared in a link keeps working when
      // a later section happens to reuse the wording.
      const seen = used.get(base) ?? 0
      used.set(base, seen + 1)
      out.push({ id: seen === 0 ? base : `${base}-${seen + 1}`, text })
    }
    index += 1
  }
  return out
}

// ---------------------------------------------------------------------------
// SEO
// ---------------------------------------------------------------------------

/** Meta descriptions are truncated to this, matching ``collectiveSeo``. */
const MAX_DESCRIPTION = 155

export function guideSeoTitle(guide: Pick<GuideArticle, 'seo_title' | 'title'>): string {
  return (guide.seo_title ?? '').trim() || guide.title
}

export function guideSeoDescription(
  guide: Pick<GuideArticle, 'seo_description' | 'standfirst'>,
): string {
  const raw = (guide.seo_description ?? '').trim() || guide.standfirst || ''
  if (raw.length <= MAX_DESCRIPTION) return raw
  const head = raw.slice(0, MAX_DESCRIPTION)
  const cut = head.lastIndexOf(' ')
  return `${(cut >= MAX_DESCRIPTION * 0.75 ? head.slice(0, cut) : head).trimEnd()}…`
}

export function guidePath(slug: string): string {
  return `/guides/${slug}`
}

/**
 * schema.org ``Article``, built from the same values the page renders.
 *
 * Returned as an object so the page serialises it once and a test can
 * assert the shape without parsing a script tag. ``dateModified``
 * comes from ``updated_at`` and ``datePublished`` from
 * ``published_at`` — an edited Guide is a changed page, and conflating
 * the two would tell a crawler nothing ever changes.
 */
export function guideJsonLd(
  guide: GuideArticle,
  origin: string,
): Record<string, unknown> {
  const url = `${origin.replace(/\/+$/, '')}${guidePath(guide.slug)}`
  const ld: Record<string, unknown> = {
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: guideSeoTitle(guide),
    description: guideSeoDescription(guide),
    url,
    mainEntityOfPage: { '@type': 'WebPage', '@id': url },
    author: {
      '@type': 'Person',
      name: (guide.author_name ?? '').trim() || HOUSE_AUTHOR,
    },
    publisher: { '@type': 'Organization', name: 'Fresh Collective' },
    dateModified: guide.updated_at,
  }
  if (guide.published_at) ld.datePublished = guide.published_at
  // Only a hero that exists. An empty ``image`` is worse than none —
  // it tells a crawler there is an image and then fails to supply one.
  if (guide.hero_image_url) {
    ld.image = guide.hero_image_url.startsWith('http')
      ? guide.hero_image_url
      : `${origin.replace(/\/+$/, '')}${guide.hero_image_url}`
  }
  return ld
}
