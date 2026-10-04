import { getMe } from '@/lib/serverApi'
import { isWaysToConnectEnabled } from '@/lib/featureFlags'

/**
 * Private production preview for the Platform Owner.
 *
 * Ways to Connect is still behind its launch flag for everybody. This
 * is the one exception: a signed-in Platform Owner can use the real
 * production feature — discovery, hello, conversations, block, report —
 * so it can be tested before the flag is flipped for all members.
 *
 * Server-only. The decision is made where the session is, so there is
 * no flag shipped to the browser that a member could flip, and nothing
 * for a query string or a cookie to influence. The owner's role comes
 * from ``/api/auth/me``, which reads the session cookie server-side.
 *
 * It mirrors the backend's ``ways_to_connect.routes.ways_to_connect_available``
 * exactly, and deliberately does not stand in for it: the API enforces
 * the same rule independently, so revealing the page could never be
 * enough on its own. If these two ever disagree the backend wins and
 * the page simply shows nothing.
 *
 * Scope is the **launch flag only**. The owner bypasses nothing else —
 * eligibility, mutual hello, thread participation and blocks are all
 * enforced for them exactly as for a member. There is no impersonation
 * here: the owner acts as themselves throughout, and sees only what
 * their own account genuinely shares with other people.
 *
 * To remove the preview once launch is approved: delete this file and
 * go back to calling ``isWaysToConnectEnabled()`` at the five call
 * sites. Nothing else depends on it.
 */
export async function waysToConnectVisible(): Promise<boolean> {
  if (isWaysToConnectEnabled()) return true
  // Platform Owner is the collapsed `admin` role — the same identity
  // the backend's ``is_platform_owner`` uses. No email match, no
  // hard-coded id.
  const me = await getMe().catch(() => null)
  return me?.role === 'admin'
}
