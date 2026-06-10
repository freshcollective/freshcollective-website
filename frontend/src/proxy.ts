import { NextResponse, type NextRequest } from 'next/server'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'

// Public space routes:
//   /spaces                                         — browse
//   /spaces/[slug]                                  — redirects to /pathways
//   /spaces/[slug]/about                            — space about page
//   /spaces/[slug]/pathways                         — pathway list (public)
//   /spaces/[slug]/pathways/[pathway-slug]/about    — pathway about/checkout page
// Everything else requires authentication.
function isSpacesRouteProtected(pathname: string): boolean {
  const segments = pathname.split('/').filter(Boolean)
  if (segments.length <= 1) return false  // /spaces
  if (segments.length === 2) return false  // /spaces/[slug]
  if (segments[2] === 'about') return false  // /spaces/[slug]/about
  if (segments[2] === 'pathways' && segments.length === 3) return false  // /spaces/[slug]/pathways
  if (segments[2] === 'pathways' && segments.length >= 5 && segments[4] === 'about') return false  // pathway about
  return true
}

const PROTECTED_PREFIXES = ['/dashboard', '/admin', '/creator', '/profile', '/settings', '/onboarding']
const AUTH_ROUTES = ['/login', '/signup', '/forgot-password', '/reset-password']

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl

  const isSpacesPath = pathname === '/spaces' || pathname.startsWith('/spaces/')
  const isProtected = isSpacesPath
    ? isSpacesRouteProtected(pathname)
    : PROTECTED_PREFIXES.some((p) => pathname.startsWith(p))
  const isAuthRoute = AUTH_ROUTES.some((r) => pathname.startsWith(r))

  if (!isProtected && !isAuthRoute) return NextResponse.next()

  const token = request.cookies.get(SESSION_COOKIE)?.value
  const authenticated = token ? await verifySessionToken(token) : false

  if (isProtected && !authenticated) {
    const url = new URL('/login', request.url)
    url.searchParams.set('next', pathname)
    return NextResponse.redirect(url)
  }

  if (isAuthRoute && authenticated) {
    return NextResponse.redirect(new URL('/dashboard', request.url))
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon\\.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)',
  ],
}
