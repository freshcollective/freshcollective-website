import { NextResponse } from 'next/server'
import { cookies } from 'next/headers'
import { revalidatePath } from 'next/cache'
import { ACTIVE_SPACE_COOKIE, getCreatorSpaces } from '@/lib/serverApi'
import { buildAbsoluteRedirectLocation } from '@/lib/absoluteRedirectLocation'
import type { SpaceSummary } from '@/types/platform'

/**
 * Set the active-collective cookie and land the creator inside that
 * collective's Home. Used by My World cards so a simple <Link>
 * can act as "switch and enter" without going through a client
 * component.
 *
 * The slug is validated against the user's own creator spaces before
 * the cookie is set — a user cannot activate a collective they don't
 * own or manage. The backend also enforces this on every downstream
 * call; the check here keeps behaviour consistent and avoids setting
 * a cookie that will only produce 403s.
 *
 * ``revalidatePath('/creator-studio', 'layout')`` invalidates the
 * cached layout tree so the sidebar (which reads the cookie server-
 * side) re-renders with the new active collective on the very next
 * navigation. Without this the client router cache serves the
 * previously-rendered layout, and the sidebar shows the old
 * collective for a beat.
 *
 * Redirect ``Location`` is an ABSOLUTE URL built via
 * ``buildAbsoluteRedirectLocation`` — see that module for the full
 * rationale. Short version: relative Location works over plain HTTP
 * but Next.js App Router's ``<Link>`` client-side navigation reads
 * the Location string through ``fetch(..., { redirect: 'manual' })``
 * and hands it to the router; any stale prefetch/cache that
 * resolves the relative string against an internal URL could still
 * misroute the browser. An absolute URL from the trusted Host header
 * bypasses every client-side resolution path.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params
  const spaces: SpaceSummary[] = await getCreatorSpaces()
  const allowed = spaces.some(s => s.slug === slug)
  if (!allowed) {
    return new NextResponse(null, {
      status: 303,
      headers: {
        Location: buildAbsoluteRedirectLocation(request, '/creator-studio'),
      },
    })
  }
  const cookieStore = await cookies()
  cookieStore.set(ACTIVE_SPACE_COOKIE, slug, {
    path: '/',
    maxAge: 60 * 60 * 24,
    httpOnly: false,
    sameSite: 'lax',
  })
  revalidatePath('/creator-studio', 'layout')
  return new NextResponse(null, {
    status: 303,
    headers: {
      Location: buildAbsoluteRedirectLocation(request, '/creator-studio/home'),
    },
  })
}
