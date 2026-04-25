import { NextResponse, type NextRequest } from 'next/server'
import { getSessionFromRequest } from '@/lib/auth/session'

// Routes that require an authenticated session
const PROTECTED_PREFIXES = ['/dashboard']

// Auth routes that logged-in users should be redirected away from
const AUTH_ROUTES = ['/login', '/signup', '/forgot-password']

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl

  const isProtected = PROTECTED_PREFIXES.some((prefix) => pathname.startsWith(prefix))
  const isAuthRoute = AUTH_ROUTES.some((route) => pathname.startsWith(route))

  if (!isProtected && !isAuthRoute) {
    return NextResponse.next()
  }

  const session = await getSessionFromRequest(request)

  if (isProtected && !session) {
    const loginUrl = new URL('/login', request.url)
    loginUrl.searchParams.set('next', pathname)
    return NextResponse.redirect(loginUrl)
  }

  if (isAuthRoute && session) {
    return NextResponse.redirect(new URL('/dashboard', request.url))
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    /*
     * Match all paths except:
     * - _next/static (static files)
     * - _next/image (image optimisation)
     * - favicon.ico
     * - Public asset file extensions
     */
    '/((?!_next/static|_next/image|favicon\\.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)',
  ],
}
