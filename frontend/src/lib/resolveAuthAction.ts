/**
 * Pure decision function for the server-side protected-route guard.
 *
 * Kept in its own module (with no Next.js runtime imports) so the
 * unit tests in ``requireAuthenticatedUser.test.ts`` can exercise
 * every branch under the built-in Node test runner + strip-types
 * — which cannot resolve ``next/headers`` / ``next/navigation``.
 *
 * The runtime wrapper is in ``requireAuthenticatedUser.ts``. It
 * collects two inputs (cookie present, live user profile from the
 * backend) and feeds them here. The backend's ``/api/auth/me`` is
 * the authoritative session check; fc-web no longer verifies JWT
 * signatures locally (SEC-002 least-privilege change).
 */

import type { UserProfile } from '@/types/platform'

export type AuthAction =
  | { action: 'render'; user: UserProfile }
  | { action: 'redirect'; to: string }

export function resolveAuthAction(input: {
  hasToken: boolean
  user: UserProfile | null
  pathname: string
  loginPath: string
}): AuthAction {
  // Any failure funnels through the same redirect shape so the ``next``
  // param is preserved consistently — no matter which check tripped.
  const failedRedirect = (): AuthAction => ({
    action: 'redirect',
    to: `${input.loginPath}?next=${encodeURIComponent(input.pathname)}`,
  })

  if (!input.hasToken) return failedRedirect()
  if (!input.user) return failedRedirect()
  return { action: 'render', user: input.user }
}
