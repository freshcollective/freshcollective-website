import type { MetadataRoute } from 'next'

import { apiUrl } from '@/lib/api'
import { SITE_ORIGIN } from '@/lib/collectiveSeo'

/**
 * The sitemap: what Fresh Collective invites a crawler to read.
 *
 * A sitemap is an invitation, so every mistake here is a privacy
 * mistake that is hard to take back once an index holds it. Two rules
 * keep it honest.
 *
 * **Collective URLs are never written down.** They come from
 * ``/api/public/sitemap/collectives``, which is built on the same
 * ``_public_space_query`` that decides what Explore shows — so a
 * Collective that is drafted, archived, made private or unpublished
 * leaves this list the moment it leaves that one, with nothing to
 * remember to update. A hand-maintained list would be correct on the
 * day it was written and wrong by the next release.
 *
 * **Visibility decides, classification only subtracts.** The endpoint
 * also drops Collectives an operator has classified ``test`` or
 * ``demonstration``. The inverse is deliberately not done: a
 * ``production`` classification is an analytics fact and is never
 * read as permission to index. That filtering happens server-side so
 * the classification itself is never published.
 *
 * **Discoverable is not indexable**, and the endpoint applies that
 * too. World Builders is reachable anonymously through a named
 * exception and has a real public About page — but that page keys
 * its own indexability on ``is_public``, which the exception leaves
 * false, so it renders ``noindex, nofollow``. Listing it would
 * invite a crawler to a page that tells it to go away. If that
 * ``noindex`` is ever judged wrong, the fix belongs in
 * ``collectiveSeo`` and the sitemap follows on its own.
 */

/**
 * One hour.
 *
 * A Collective being published is not news a crawler needs within
 * seconds, and the alternative — rebuilding this on every request —
 * puts an uncacheable database query in front of anything that asks,
 * including things that ask often and are not search engines.
 */
export const revalidate = 3600

interface SitemapCollective {
  slug: string
  /** ``spaces.updated_at``: a real recorded change, not "now". */
  updated_at: string
}

/**
 * The public pages that are not Collectives.
 *
 * Listed explicitly rather than discovered from the filesystem: most
 * routes under ``src/app`` are signed-in surfaces, and a rule that
 * tried to tell them apart automatically would eventually be wrong in
 * the direction that matters. Adding a public page here is one line,
 * and a reviewer can see what is being offered to a crawler.
 *
 * Deliberately absent, and why:
 *
 *   /creator-onboarding   declares ``robots: noindex``
 *   /messages             declares ``robots: noindex``
 *   /build-your-place     a redirect to /build-your-collective
 *   /build-your-collective a creator flow, driven by query strings
 *   /tnlbook123           declares ``robots: noindex`` — the Book
 *                         Companion is for a reader who already has
 *                         the printed URL, not for a search result.
 *                         Deliberately still crawlable: robots.txt
 *                         must not close it, or the crawler never
 *                         reads the ``noindex`` it is being told.
 *   /login /signup /verify-email /forgot-password /reset-password
 *                         authentication, not destinations
 *   /dashboard /settings /profile /notifications /checkout /invites
 *   /creator-studio /creator /admin /onboarding /api /dev
 *                         signed-in or internal
 *
 * No ``lastModified``. These change when the code changes, and the
 * only timestamp available would be the build — which would tell a
 * crawler that every page changed on every deploy, including the
 * ones that did not.
 */
const PUBLIC_PAGES = [
  '/',
  '/about',
  '/for-creators',
  '/membership',
  '/real-journey',
  '/discover-places',
  '/leadershipbodychart',
  '/tnlbook',
  '/ecosystem-interest',
] as const

/**
 * Collectives whose About page may be indexed.
 *
 * Returns an empty list rather than throwing if the API is
 * unreachable. A sitemap missing its Collective entries for an hour
 * is a crawler finding them a little later; a sitemap that 500s is
 * one a search engine may stop fetching. Neither outcome publishes
 * anything private, which is the property that actually matters.
 */
async function publicCollectives(): Promise<SitemapCollective[]> {
  try {
    const res = await fetch(apiUrl('/api/public/sitemap/collectives'), {
      next: { revalidate },
    })
    if (!res.ok) return []
    const rows: unknown = await res.json()
    if (!Array.isArray(rows)) return []
    return rows.filter(
      (r): r is SitemapCollective =>
        typeof r?.slug === 'string' &&
        r.slug.length > 0 &&
        typeof r?.updated_at === 'string',
    )
  } catch {
    return []
  }
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const collectives = await publicCollectives()

  const entries: MetadataRoute.Sitemap = [
    ...PUBLIC_PAGES.map((path) => ({ url: `${SITE_ORIGIN}${path}` })),
    ...collectives.map((c) => ({
      // The canonical the About page declares for itself — not
      // ``/spaces/{slug}``, which redirects a non-member here and
      // would make the two look like duplicates of each other.
      url: `${SITE_ORIGIN}/spaces/${encodeURIComponent(c.slug)}/about`,
      lastModified: new Date(c.updated_at),
    })),
  ]

  // A duplicate would be a bug upstream rather than something to
  // tolerate, but a sitemap is the wrong place to find out.
  const seen = new Set<string>()
  return entries.filter((e) => {
    if (seen.has(e.url)) return false
    seen.add(e.url)
    return true
  })
}
