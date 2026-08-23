/**
 * `requireAuthenticatedUser` — the single server-side auth guard used by
 * every protected layout / server page.
 *
 * The Next.js middleware in ``src/proxy.ts`` performs a cheap check:
 * it verifies the JWT's signature and expiry via ``verifySessionToken``.
 * That is fast and cache-friendly, but it does not know whether the
 * user row referenced by the token still exists — a rolled-back test
 * account, a deleted user, or a revoked session all leave a valid
 * signature behind.
 *
 * Without a per-page guard, such a stale-but-signed cookie sails past
 * the middleware and lands on a protected page whose ``getMe()`` returns
 * ``null``. The page then renders with fallback strings ("friend") and
 * empty data — a jarring, half-authenticated UX.
 *
 * This helper closes that gap in exactly one place. Each protected
 * server layout calls ``requireAuthenticatedUser()`` at the top; on
 * any failure it issues a ``redirect(...)`` so the page never renders
 * with a null user. The returned ``UserProfile`` can be threaded into
 * the layout's shell (e.g. Creator Studio uses the role for gating).
 *
 * The ``next`` query parameter preserves the requested URL so the
 * user lands where they intended after logging in. It is read from
 * the ``x-pathname`` request header the proxy middleware sets on
 * every request (see ``src/proxy.ts::proxy``).
 *
 * The pure decision function ``resolveAuthAction`` is exported so
 * unit tests can cover every branch without needing to mock
 * ``next/headers`` / ``next/navigation``.
 */

import { cookies, headers } from 'next/headers'
import { redirect } from 'next/navigation'

import { resolveAuthAction } from './resolveAuthAction'
import { getMe } from './serverApi'
import { SESSION_COOKIE, verifySessionToken } from './session'
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
  const signatureValid = hasToken ? await verifySessionToken(token as string) : false
  const user = signatureValid ? await _loadUser() : null
  const pathname = await _currentPathname(fallbackNext)

  const decision = resolveAuthAction({
    hasToken, signatureValid, user, pathname, loginPath,
  })

  if (decision.action === 'redirect') {
    redirect(decision.to)
  }
  return decision.user
}
