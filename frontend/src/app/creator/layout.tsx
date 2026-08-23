import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import { requireAuthenticatedUser } from '@/lib/requireAuthenticatedUser'
import { getCreatorSpaces, ACTIVE_SPACE_COOKIE } from '@/lib/serverApi'
import CreatorStudioShell from '@/app/creator-studio/CreatorStudioShell'
import type { SpaceSummary } from '@/types/platform'

// Legacy /creator/spaces/... routes now render inside the same Creator Studio
// shell as /creator-studio/... so the sidebar is consistent everywhere.
export default async function CreatorLayout({ children }: { children: React.ReactNode }) {
  // Shared guard: a null user (deleted / rolled-back account) redirects
  // to /login with the intended destination preserved as ``next``. A
  // wrong role (authenticated member) then falls through to /dashboard,
  // preserving the previous "non-creator has nothing to do here" behaviour.
  const profile = await requireAuthenticatedUser()
  if (!['creator', 'admin'].includes(profile.role)) {
    redirect('/dashboard')
  }

  const cookieStore = await cookies()
  const spaces: SpaceSummary[] = await getCreatorSpaces()
  const activeSlug = cookieStore.get(ACTIVE_SPACE_COOKIE)?.value
  const activeSpace = (activeSlug ? spaces.find((s) => s.slug === activeSlug) : null) ?? spaces[0] ?? null

  return (
    <CreatorStudioShell user={profile} hasCollective={!!activeSpace}>
      {children}
    </CreatorStudioShell>
  )
}
