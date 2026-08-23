/**
 * Pure decision function for the server-side protected-route guard.
 *
 * Kept in its own module (with no Next.js runtime imports) so the
 * unit tests in ``requireAuthenticatedUser.test.ts`` can exercise
 * every branch under the built-in Node test runner + strip-types
 * — which cannot resolve ``next/headers`` / ``next/navigation``.
 *
 * The runtime wrapper is in ``requireAuthenticatedUser.ts``. It
 * collects the three inputs (cookie present, JWT signature valid,
 * live user profile) and feeds them here.
 */

import type { UserProfile } from '@/types/platform'

export type AuthAction =
  | { action: 'render'; user: UserProfile }
  | { action: 'redirect'; to: string }

export function resolveAuthAction(input: {
  hasToken: boolean
  signatureValid: boolean
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
  if (!input.signatureValid) return failedRedirect()
  if (!input.user) return failedRedirect()
  return { action: 'render', user: input.user }
}
