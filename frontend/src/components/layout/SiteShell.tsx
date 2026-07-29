import { ReactNode } from 'react'
import { cookies } from 'next/headers'
import { SESSION_COOKIE } from '@/lib/session'
import { apiUrl } from '@/lib/api'
import { isDiscoveryPillarEnabled } from '@/lib/featureFlags'
import PublicHeader from './PublicHeader'
import PublicFooter from './PublicFooter'
import WorldHeader from './WorldHeader'

/**
 * SiteShell — the shared shell for pages that carry the public/marketing
 * chrome (PublicHeader + PublicFooter).
 *
 * Auth-aware: when a visitor is signed in, the public header is
 * swapped for WorldHeader so an authenticated member sees the same
 * persistent member navigation across every surface. The footer
 * stays either way — retaining existing behaviour for pages that
 * used SiteShell before this change.
 *
 * The homepage (/) is the one deliberate exception: it stays public
 * for everyone by passing `publicOnly`. It remains the public front
 * door; signed-in visitors still see a "Your World" link inside the
 * public header.
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

export default async function SiteShell({
  children,
  heroHeader = false,
  publicOnly = false,
  noFooter = false,
}: {
  children: ReactNode
  heroHeader?: boolean
  /** Force the public header regardless of auth. Used by the
   *  homepage, which stays the public front door for everyone. */
  publicOnly?: boolean
  /** Skip the public footer. Used by contexts like inside-Collective
   *  layouts that already carry their own bottom chrome and would
   *  feel odd bookended by the marketing footer. */
  noFooter?: boolean
}) {
  const user = publicOnly ? null : await getCurrentUser()
  const useWorld = !publicOnly && user !== null

  if (heroHeader) {
    // Hero (overlay) header is only used by public marketing pages
    // like the homepage — WorldHeader has no overlay variant because
    // no member surface uses it. Fall back to PublicHeader in overlay
    // mode even for authenticated visitors on such a page.
    return (
      <div className="relative">
        <PublicHeader overlay />
        <main className="flex-1">{children}</main>
        {!noFooter && <PublicFooter />}
      </div>
    )
  }

  return (
    <>
      {useWorld && user
        ? <WorldHeader user={{ name: user.name, role: user.role }} discoveryOn={isDiscoveryPillarEnabled()} />
        : <PublicHeader />}
      <main className="flex-1">{children}</main>
      {!noFooter && <PublicFooter />}
    </>
  )
}
