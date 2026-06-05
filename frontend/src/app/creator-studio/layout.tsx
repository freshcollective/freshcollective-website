import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'
import {
  getMe,
  getCreatorSpaces,
  getCreatorBilling,
  getCreatorPathways,
  getCreatorEvents,
  getCreatorMembers,
  getCreatorInvitations,
  getCreatorAccessRequests,
  ACTIVE_SPACE_COOKIE,
} from '@/lib/serverApi'
import CreatorStudioShell from './CreatorStudioShell'
import type { LiteData } from './CreatorStudioLiteMobile'
import type { SpaceSummary, CreatorPathway, CreatorEvent, CreatorMemberDetail, SpaceInvitation, AccessRequest } from '@/types/platform'

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

  const billing = await getCreatorBilling()
  const collectiveLimit = billing?.current_plan.collective_limit ?? 1

  // Fetch lite data for the mobile Creator Studio Lite view.
  // Runs in parallel; any individual failure degrades gracefully to empty.
  const liteData: LiteData = {
    pathwayCounts: { published: 0, comingSoon: 0, drafts: 0, archived: 0 },
    upcomingGatherings: [],
    memberCount: 0,
    leaderCount: 0,
    pendingInvites: 0,
    pendingRequests: 0,
  }

  if (activeSpace) {
    const [pathwaysResult, eventsResult, membersResult, invitesResult, requestsResult] =
      await Promise.allSettled([
        getCreatorPathways(activeSpace.slug) as Promise<CreatorPathway[]>,
        getCreatorEvents(activeSpace.slug) as Promise<CreatorEvent[]>,
        getCreatorMembers(activeSpace.slug) as Promise<CreatorMemberDetail[]>,
        getCreatorInvitations(activeSpace.slug) as Promise<SpaceInvitation[]>,
        getCreatorAccessRequests(activeSpace.slug) as Promise<AccessRequest[]>,
      ])

    const pathways = pathwaysResult.status === 'fulfilled' ? pathwaysResult.value : []
    const events   = eventsResult.status === 'fulfilled'   ? eventsResult.value   : []
    const members  = membersResult.status === 'fulfilled'  ? membersResult.value  : []
    const invites  = invitesResult.status === 'fulfilled'  ? invitesResult.value  : []
    const requests = requestsResult.status === 'fulfilled' ? requestsResult.value : []

    const now = Date.now()

    liteData.pathwayCounts = {
      published:  pathways.filter(p => p.status === 'active').length,
      comingSoon: pathways.filter(p => p.status === 'coming_soon').length,
      drafts:     pathways.filter(p => p.status === 'draft').length,
      archived:   pathways.filter(p => p.status === 'archived').length,
    }

    liteData.upcomingGatherings = events
      .filter(e => e.status === 'active' && new Date(e.starts_at).getTime() >= now)
      .sort((a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime())
      .slice(0, 5)
      .map(e => ({
        id: e.id,
        title: e.title,
        starts_at: e.starts_at,
        booked_count: e.booked_count,
        capacity: e.capacity,
      }))

    liteData.memberCount   = members.filter(m => m.space_role === 'learner').length
    liteData.leaderCount   = members.filter(m => m.space_role === 'creator' || m.space_role === 'moderator').length
    liteData.pendingInvites  = invites.length
    liteData.pendingRequests = requests.filter(r => r.status === 'pending').length
  }

  return (
    <CreatorStudioShell
      user={profile}
      spaces={spaces}
      activeSpace={activeSpace}
      collectiveLimit={collectiveLimit}
      liteData={liteData}
    >
      {children}
    </CreatorStudioShell>
  )
}
