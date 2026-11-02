import type { MetadataRoute } from 'next'

import { SITE_ORIGIN } from '@/lib/collectiveSeo'

/**
 * robots.txt — guidance for crawlers, and nothing more.
 *
 * **This is not access control and must never be relied on as any.**
 * Every path below is already protected by the application's own
 * authentication and authorisation; a crawler that ignores this file
 * gets the same 401 or 404 a stranger does. What it buys is that
 * well-behaved crawlers do not spend their budget on pages that will
 * refuse them, and that signed-in surfaces stay out of an index by
 * accident of a shared link.
 *
 * There is a real hazard in writing it, which is why the disallowed
 * list is specific rather than broad: a prefix that was a little too
 * generous would quietly delist the public Collective About pages
 * the sitemap exists to advertise. ``/spaces`` in particular is **not**
 * disallowed — it is where the public pages live.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        disallow: [
          // World Management and everything under it.
          '/admin/',
          // Creator-only surfaces.
          '/creator-studio/',
          '/creator/',
          '/creator-onboarding',
          '/build-your-collective',
          '/build-your-place',
          // A member's own account and their private areas.
          '/dashboard/',
          '/settings/',
          '/profile/',
          '/notifications/',
          '/messages/',
          // Transactional and invitation flows. Nothing here is a
          // destination, and an invite path carries a token.
          '/checkout/',
          '/invites/',
          '/onboarding/',
          // Authentication. Crawling these achieves nothing and a
          // reset path carries a single-use token.
          '/login',
          '/signup',
          '/verify-email',
          '/forgot-password',
          '/reset-password',
          // The BFF proxy and the development-only previews.
          '/api/',
          '/dev/',
        ],
      },
    ],
    // Absolute, as the specification requires — a relative sitemap
    // reference is ignored.
    sitemap: `${SITE_ORIGIN}/sitemap.xml`,
    host: SITE_ORIGIN,
  }
}
