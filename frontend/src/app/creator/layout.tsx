import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'
import { getMe, getCreatorSpaces, getCreatorBilling, ACTIVE_SPACE_COOKIE } from '@/lib/serverApi'
import CreatorStudioShell from '@/app/creator-studio/CreatorStudioShell'
import type { SpaceSummary } from '@/types/platform'

// Legacy /creator/spaces/... routes now render inside the same Creator Studio
// shell as /creator-studio/... so the sidebar is consistent everywhere.
export default async function CreatorLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value
  const authenticated = token ? await verifySessionToken(token) : false
  if (!authenticated) redirect('/login')

  const profile = await getMe()
  if (!profile || !['creator', 'admin'].includes(profile.role)) {
    redirect('/dashboard')
  }

  const spaces: SpaceSummary[] = await getCreatorSpaces()
  const activeSlug = cookieStore.get(ACTIVE_SPACE_COOKIE)?.value
  const activeSpace = (activeSlug ? spaces.find((s) => s.slug === activeSlug) : null) ?? spaces[0] ?? null

  const billing = await getCreatorBilling()
  const isPlatformOwner = billing?.is_platform_owner ?? false
  const collectiveLimit = billing?.current_plan?.collective_limit ?? 1

  return (
    <CreatorStudioShell
      user={profile}
      spaces={spaces}
      activeSpace={activeSpace}
      collectiveLimit={collectiveLimit}
      isPlatformOwner={isPlatformOwner}
    >
      {children}
    </CreatorStudioShell>
  )
}
