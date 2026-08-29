/**
 * `requireAuthenticatedUser` — the single server-side auth guard used by
 * every protected layout / server page.
 *
 * The middleware in ``src/proxy.ts`` performs cookie-presence routing
 * only (SEC-002 least-privilege change — fc-web no longer holds the
 * JWT signing key). This helper is the authoritative check: it asks the
 * backend for the live user via ``getMe()`` (``/api/auth/me``), and if
 * that returns null it redirects to the login door with the requested
 * URL preserved in ``next``.
 *
 * That means a stale, forged, or otherwise unusable cookie will sail
 * past the middleware and be caught here — the backend is the sole
 * authority for whether a session is real.
 *
 * The pure decision function ``resolveAuthAction`` is exported so
 * unit tests can cover every branch without needing to mock
 * ``next/headers`` / ``next/navigation``.
 */

import { cookies, headers } from 'next/headers'
import { redirect } from 'next/navigation'

import { resolveAuthAction } from './resolveAuthAction'
import { getMe } from './serverApi'
import { SESSION_COOKIE } from './session'
import type { UserProfile } from '@/types/platform'

// Re-export for callers that already import from this module.
export type { AuthAction } from './resolveAuthAction'
export { resolveAuthAction } from './resolveAuthAction'

interface RequireAuthOptions {
  /** Login destination when the guard fails. Defaults to ``/login``.
   *  Admin surfaces pass ``/admin/login`` so administrators land on
   *  the correct door. */
  loginPath?: string
  /** Explicit fallback ``next`` value when the ``x-pathname`` header is
   *  not present (rare — happens during a direct programmatic render
   *  outside a request context). */
  fallbackNext?: string
}

async function _currentPathname(fallback: string): Promise<string> {
  const h = await headers()
  return h.get('x-pathname') ?? fallback
}

async function _loadUser(): Promise<UserProfile | null> {
  // Uses the shared React-cached ``getMe()`` so pages/layouts under
  // the same request that also call ``getMe`` see a single deduped
  // /api/auth/me round-trip.
  try {
    return (await getMe()) as UserProfile | null
  } catch {
    return null
  }
}

/** Resolve the live authenticated user for a protected server layout /
 *  page, or ``redirect`` to the login door with a preserved ``next`` param.
 *
 *  Never returns ``null`` — a null result would let callers accidentally
 *  render with no user (the very bug this helper exists to prevent). */
export async function requireAuthenticatedUser(
  options: RequireAuthOptions = {},
): Promise<UserProfile> {
  const loginPath = options.loginPath ?? '/login'
  const fallbackNext = options.fallbackNext ?? '/dashboard'

  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value
  const hasToken = !!token
  // No local signature check — the backend is authoritative. If the
  // cookie is missing or the backend rejects it, ``_loadUser`` returns
  // null and the decision function issues a redirect.
  const user = hasToken ? await _loadUser() : null
  const pathname = await _currentPathname(fallbackNext)

  const decision = resolveAuthAction({
    hasToken, user, pathname, loginPath,
  })

  if (decision.action === 'redirect') {
    redirect(decision.to)
  }
  return decision.user
}
