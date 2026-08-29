import { NextResponse, type NextRequest } from 'next/server'
import { SESSION_COOKIE } from '@/lib/session'
import { ACTIVE_SPACE_COOKIE } from '@/lib/activeSpaceCookie'
import { decide, extractCreatorSpaceSlug } from '@/proxyRouting'

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl
  // Presence-only auth check (SEC-002). The authoritative session check
  // lives in ``requireAuthenticatedUser`` on the backend side via
  // ``/api/auth/me``; the middleware only needs to know whether a
  // session cookie is present so it can route unauthenticated visitors
  // to the correct login door. This removes the dependency on the JWT
  // signing secret from fc-web.
  const authenticated = !!request.cookies.get(SESSION_COOKIE)?.value

  const decision = decide(pathname, authenticated)
  if (decision.action === 'next') {
    // Expose the request pathname to server components via a request
    // header. App Router does not give layouts/pages the current
    // pathname directly; the admin layout needs it to skip its auth
    // guard for /admin/login (otherwise the layout would redirect the
    // login page back to itself in a loop).
    const forwardHeaders = new Headers(request.headers)
    forwardHeaders.set('x-pathname', pathname)

    // Active-collective sync — URL is authoritative on /creator/spaces/[slug].
    // The sidebar identifies the active collective from the cookie, while
    // pages under /creator/spaces/[slug] identify it from params. When they
    // disagree, the sidebar shows a different collective from the page. We
    // rewrite the request cookie so the layout renders THIS request with
    // the correct slug, and set a response cookie so the browser stays in
    // sync for every subsequent navigation.
    const urlSlug = extractCreatorSpaceSlug(pathname)
    const cookieSlug = request.cookies.get(ACTIVE_SPACE_COOKIE)?.value
    if (urlSlug && urlSlug !== cookieSlug) {
      request.cookies.set(ACTIVE_SPACE_COOKIE, urlSlug)
      const response = NextResponse.next({ request: { headers: forwardHeaders } })
      response.cookies.set(ACTIVE_SPACE_COOKIE, urlSlug, {
        path: '/',
        maxAge: 60 * 60 * 24,
        sameSite: 'lax',
      })
      return response
    }

    return NextResponse.next({ request: { headers: forwardHeaders } })
  }

  const url = new URL(decision.to, request.url)
  if (decision.next) url.searchParams.set('next', decision.next)
  return NextResponse.redirect(url)
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon\\.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)',
  ],
}
