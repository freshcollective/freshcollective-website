/**
 * Pure routing logic for the proxy (middleware).
 *
 * Extracted from ``proxy.ts`` so it can be unit-tested without pulling
 * in ``next/server``. The proxy's runtime shim in ``proxy.ts`` composes
 * these helpers with the request cookie and issues the redirect.
 *
 * The single most important invariant enforced here:
 *
 *   ``/admin/login`` is a PUBLIC auth page, even though it sits under
 *   the ``/admin`` protected prefix. Auth-route matching happens BEFORE
 *   protected-prefix matching so the admin door is always reachable.
 */

// Public /spaces routes:
//   /spaces                                         — browse
//   /spaces/[slug]                                  — redirects to /pathways
//   /spaces/[slug]/about                            — space about page
//   /spaces/[slug]/pathways                         — pathway list (public)
//   /spaces/[slug]/pathways/[pathway-slug]/about    — pathway about page
//   /spaces/[slug]/pathways/[pathway-slug]/checkout — checkout entry (option selection)
// Everything else under /spaces requires authentication.
function isSpacesRouteProtected(pathname: string): boolean {
  const segments = pathname.split('/').filter(Boolean)
  if (segments.length <= 1) return false
  if (segments.length === 2) return false
  if (segments[2] === 'about') return false
  if (segments[2] === 'pathways' && segments.length === 3) return false
  if (segments[2] === 'pathways' && segments.length >= 5 && segments[4] === 'about') return false
  if (segments[2] === 'pathways' && segments.length >= 5 && segments[4] === 'checkout') return false
  return true
}

/**
 * Public authentication routes — reachable while signed out. Match is
 * exact-path (with optional trailing slash), never prefix, so an
 * accidentally-named descendant route can never leak past the auth
 * guard.
 */
const AUTH_ROUTES: ReadonlySet<string> = new Set([
  '/login',
  '/signup',
  '/forgot-password',
  '/reset-password',
  '/admin/login',
])

/**
 * Protected top-level roots. Matched with a segment-boundary check
 * (``pathname === prefix`` or ``pathname.startsWith(prefix + '/')``) so
 * we never treat ``/creatorstudio`` as a member of ``/creator``.
 *
 * ``/creator`` and ``/creator-studio`` are separate top-level roots and
 * both appear here explicitly.
 */
const PROTECTED_PREFIXES: readonly string[] = [
  '/dashboard',
  '/admin',
  '/creator',
  '/creator-studio',
  '/profile',
  '/settings',
  '/onboarding',
]

function normalize(pathname: string): string {
  return pathname !== '/' && pathname.endsWith('/') ? pathname.slice(0, -1) : pathname
}

export function isAuthRoute(pathname: string): boolean {
  return AUTH_ROUTES.has(normalize(pathname))
}

export function isProtectedRoute(pathname: string): boolean {
  const p = normalize(pathname)
  // Auth pages are never protected, even when they sit under a
  // protected prefix (e.g. /admin/login lives under /admin).
  if (AUTH_ROUTES.has(p)) return false
  if (p === '/spaces' || p.startsWith('/spaces/')) {
    return isSpacesRouteProtected(p)
  }
  return PROTECTED_PREFIXES.some((prefix) => p === prefix || p.startsWith(prefix + '/'))
}

/** Login destination for a given protected pathname. */
export function loginPathFor(pathname: string): string {
  const p = normalize(pathname)
  return p === '/admin' || p.startsWith('/admin/') ? '/admin/login' : '/login'
}

/**
 * Restrict the ``next`` parameter so the admin door cannot bounce a
 * caller into a non-admin URL. Non-admin ``next`` values pass through
 * unchanged; the target auth page validates them again.
 */
export function safeNextFor(loginPath: string, pathname: string): string {
  if (loginPath !== '/admin/login') return pathname
  return pathname === '/admin' || pathname.startsWith('/admin/') ? pathname : '/admin'
}

/**
 * Pure routing decision for a given (pathname, authenticated) pair.
 * Exported for unit testing.
 */
export type ProxyDecision =
  | { action: 'next' }
  | { action: 'redirect'; to: string; next?: string }

export function decide(pathname: string, authenticated: boolean): ProxyDecision {
  const protectedRoute = isProtectedRoute(pathname)
  const authRoute = isAuthRoute(pathname)

  if (!protectedRoute && !authRoute) return { action: 'next' }

  if (protectedRoute && !authenticated) {
    const to = loginPathFor(pathname)
    return { action: 'redirect', to, next: safeNextFor(to, pathname) }
  }

  if (authRoute && authenticated) {
    // ``/admin/login`` handles signed-in callers itself: admins are
    // forwarded to ``/admin`` by the page's own guard; non-admins see a
    // clear "administrators only" message from the form. Letting the
    // page render avoids a middleware→layout→middleware loop for the
    // non-admin case.
    if (normalize(pathname) === '/admin/login') return { action: 'next' }
    return { action: 'redirect', to: '/dashboard' }
  }

  return { action: 'next' }
}
