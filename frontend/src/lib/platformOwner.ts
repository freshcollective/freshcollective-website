import { getMe } from '@/lib/serverApi'

/**
 * Is the current viewer the Platform Owner?
 *
 * Server-only, and the single frontend definition of that question —
 * mirroring the backend's ``plan_guards.is_platform_owner``, which is
 * the documented source of truth. Platform Owner is the collapsed
 * ``admin`` role until the Platform Admin / Owner split lands.
 *
 * The role comes from the session via ``/api/auth/me``, so there is
 * nothing a member can set: no query string, no cookie of their own, no
 * email comparison, no hard-coded id. A failed lookup denies.
 */
export async function viewerIsPlatformOwner(): Promise<boolean> {
  const me = await getMe().catch(() => null)
  return me?.role === 'admin'
}
