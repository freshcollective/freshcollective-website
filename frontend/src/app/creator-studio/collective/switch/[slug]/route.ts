import { NextResponse } from 'next/server'
import { cookies } from 'next/headers'
import { revalidatePath } from 'next/cache'
import { ACTIVE_SPACE_COOKIE, getCreatorSpaces } from '@/lib/serverApi'
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
 * Redirect targets are RELATIVE, deliberately. Route Handlers on
 * Render receive a ``request.url`` whose host is the container's
 * internal listen address (``http://localhost:$PORT``); constructing
 * ``new URL('/x', request.url)`` and returning that in a
 * ``Location`` header would send the browser to
 * ``http://localhost:10000/x`` in production. Per RFC 7231 §7.1.2,
 * a relative ``Location`` is resolved against the effective request
 * URI from the browser's perspective (i.e. the public origin), which
 * is the behaviour we want here. Every real browser handles this
 * correctly.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params
  const spaces: SpaceSummary[] = await getCreatorSpaces()
  const allowed = spaces.some(s => s.slug === slug)
  if (!allowed) {
    return new NextResponse(null, {
      status: 303,
      headers: { Location: '/creator-studio' },
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
    headers: { Location: '/creator-studio/home' },
  })
}
