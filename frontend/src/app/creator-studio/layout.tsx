import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'
import { getMe, getCreatorSpaces, ACTIVE_SPACE_COOKIE } from '@/lib/serverApi'
import CreatorStudioShell from './CreatorStudioShell'
import type { SpaceSummary } from '@/types/platform'

export const metadata = { title: 'Creator Studio — Fresh Collective' }

export default async function CreatorStudioLayout({ children }: { children: React.ReactNode }) {
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
  const activeSpace = (activeSlug ? spaces.find(s => s.slug === activeSlug) : null) ?? spaces[0] ?? null

  return (
    <CreatorStudioShell user={profile} spaces={spaces} activeSpace={activeSpace}>
      {children}
    </CreatorStudioShell>
  )
}
