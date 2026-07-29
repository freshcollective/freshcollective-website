import { ReactNode } from 'react'
import { cookies } from 'next/headers'
import { SESSION_COOKIE } from '@/lib/session'
import { apiUrl } from '@/lib/api'
import { isDiscoveryPillarEnabled } from '@/lib/featureFlags'
import WorldHeader from './WorldHeader'

/**
 * WorldShell — the persistent shell for authenticated member surfaces.
 *
 * Sibling to SiteShell (which serves marketing / public surfaces).
 * This one mounts `WorldHeader` and leaves the footer off — member
 * pages do not carry the marketing chrome.
 *
 * Used by:
 *   - dashboard/layout.tsx        (Your World)
 *   - settings/layout.tsx         (Settings, stacked above SettingsNav)
 *   - notifications/layout.tsx    (Notifications)
 *   - profile/layout.tsx          (Member profile)
 *   - spaces/[slug]/layout.tsx    (stacked above the Collective chrome)
 *
 * Pages that already use SiteShell (Explore Collectives, Discover
 * Places, Ways to Connect, Membership) get WorldHeader automatically
 * for authenticated visitors via SiteShell's auth-aware selection —
 * they should not also wrap in WorldShell.
 */

interface MeResponse {
  id: string
  email: string
  name: string | null
  role: string
}

async function getCurrentUser(): Promise<MeResponse | null> {
  const cookieStore = await cookies()
  const session = cookieStore.get(SESSION_COOKIE)
  if (!session) return null
  try {
    const res = await fetch(apiUrl('/api/auth/me'), {
      headers: { Cookie: `${SESSION_COOKIE}=${session.value}` },
      cache: 'no-store',
    })
    if (!res.ok) return null
    return res.json() as Promise<MeResponse>
  } catch {
    return null
  }
}

export default async function WorldShell({ children }: { children: ReactNode }) {
  const user = await getCurrentUser()
  const discoveryOn = isDiscoveryPillarEnabled()

  // If the visitor is not authenticated, WorldShell renders no chrome.
  // Auth-guarded layouts (dashboard/layout.tsx etc.) already redirect
  // to /login before we reach this point, so this branch is a safety
  // net rather than a real code path.
  if (!user) {
    return <main className="flex-1">{children}</main>
  }

  return (
    <>
      <WorldHeader
        user={{ name: user.name, role: user.role }}
        discoveryOn={discoveryOn}
      />
      <main className="flex-1">{children}</main>
    </>
  )
}
