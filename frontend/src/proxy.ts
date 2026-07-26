import { NextResponse, type NextRequest } from 'next/server'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'
import { decide } from '@/proxyRouting'

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl
  const token = request.cookies.get(SESSION_COOKIE)?.value
  const authenticated = token ? await verifySessionToken(token) : false

  const decision = decide(pathname, authenticated)
  if (decision.action === 'next') {
    // Expose the request pathname to server components via a request
    // header. App Router does not give layouts/pages the current
    // pathname directly; the admin layout needs it to skip its auth
    // guard for /admin/login (otherwise the layout would redirect the
    // login page back to itself in a loop).
    const forwardHeaders = new Headers(request.headers)
    forwardHeaders.set('x-pathname', pathname)
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
