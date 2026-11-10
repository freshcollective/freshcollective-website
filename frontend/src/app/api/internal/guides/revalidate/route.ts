import { revalidatePath, revalidateTag } from 'next/cache'
import { NextResponse } from 'next/server'

import { GUIDES_TAG } from '@/app/sitemap'
import { serverFetch } from '@/lib/serverApi'

/**
 * Clear the Guides caches after an admin action.
 *
 * ``/guides`` and ``/guides/[slug]`` do not need this — they are
 * uncached and already reflect the database on the next request.
 * ``/sitemap.xml`` does: it is statically generated with an hourly
 * revalidate, shared with the Collectives listing, and making the
 * whole file dynamic would put a database query in front of
 * everything that asks for it, which is the arrangement that file
 * documents at length for good reasons.
 *
 * So this is a nudge for one cached artefact, not the mechanism that
 * makes publishing work. If it fails, the sitemap is up to an hour
 * stale and nothing else is affected — no Guide is wrongly readable
 * and no withdrawn Guide stays up. That is why the admin treats a
 * failure here as worth no interruption.
 *
 * **Admin-only, and that is the point of a route handler rather than
 * a public endpoint.** Cache invalidation is not destructive, but an
 * endpoint anyone could call is an endpoint anyone could call in a
 * loop, turning a cached file into an uncached one on someone else's
 * schedule. Authorisation is the same check the rest of the admin
 * uses: the session cookie is forwarded to ``/api/auth/me`` and the
 * answer has to be an administrator. Nothing is trusted from the
 * request body — there is no body.
 */
export async function POST(): Promise<NextResponse> {
  let role: string | null = null
  try {
    const me = await serverFetch('/api/auth/me')
    if (me.ok) {
      const user = (await me.json()) as { role?: string }
      role = user?.role ?? null
    }
  } catch {
    // Treated as "not an administrator" below. A backend that cannot
    // answer is not permission to clear a cache.
    role = null
  }

  if (role !== 'admin') {
    return NextResponse.json(
      { detail: 'Admin access required.' },
      { status: 403 },
    )
  }

  // Both, and both are needed. ``revalidatePath`` purges the
  // generated route, but regenerating it re-runs a fetch whose own
  // Data Cache entry is still inside its hour — so the file would
  // rebuild from stale data and look like the invalidation had
  // failed. The tag expires that entry. ``{ expire: 0 }`` rather
  // than a named cache-life profile: the intent is "now", and it
  // does not depend on which profiles this Next version ships.
  revalidateTag(GUIDES_TAG, { expire: 0 })
  revalidatePath('/sitemap.xml')

  return NextResponse.json({ revalidated: true })
}
