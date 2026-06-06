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
  getCreatorResources,
  ACTIVE_SPACE_COOKIE,
} from '@/lib/serverApi'
import CreatorStudioShell from './CreatorStudioShell'
import type { LiteData, LiteBillingData } from './CreatorStudioLiteMobile'
import type {
  SpaceSummary,
  CreatorPathway,
  CreatorEvent,
  CreatorMemberDetail,
  SpaceInvitation,
  AccessRequest,
  CreatorResource,
} from '@/types/platform'

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

  // Map billing data for the Lite mobile view (already fetched above).
  const liteBilling: LiteBillingData | null = billing ? {
    planName: billing.current_plan.name,
    monthlyPriceCents: billing.current_plan.monthly_price_cents,
    currency: billing.current_plan.currency,
    transactionFeeBasisPoints: billing.current_plan.transaction_fee_basis_points,
    creatorBillingConnected: billing.payment_setup.creator_billing_connected,
    memberPaymentsConnected: billing.payment_setup.member_payments_connected,
    stripeConnectConnected: billing.payment_setup.stripe_connect_connected,
    collectivesUsed: billing.usage.collectives_used,
    collectiveLimit: billing.current_plan.collective_limit,
  } : null

  // Fetch data for the mobile Creator Studio Lite view in parallel.
  // Any individual failure degrades gracefully to an empty value.
  const liteData: LiteData = {
    pathwayCounts: { published: 0, comingSoon: 0, drafts: 0, archived: 0 },
    publishedPathways: [],
    allPathways: [],
    upcomingGatherings: [],
    memberCount: 0,
    leaderCount: 0,
    members: [],
    invitations: [],
    accessRequests: [],
    pendingInvites: 0,
    pendingRequests: 0,
    resourceCount: 0,
    billing: liteBilling,
  }

  if (activeSpace) {
    const [pathwaysResult, eventsResult, membersResult, invitesResult, requestsResult, resourcesResult] =
      await Promise.allSettled([
        getCreatorPathways(activeSpace.slug) as Promise<CreatorPathway[]>,
        getCreatorEvents(activeSpace.slug) as Promise<CreatorEvent[]>,
        getCreatorMembers(activeSpace.slug) as Promise<CreatorMemberDetail[]>,
        getCreatorInvitations(activeSpace.slug) as Promise<SpaceInvitation[]>,
        getCreatorAccessRequests(activeSpace.slug) as Promise<AccessRequest[]>,
        getCreatorResources(activeSpace.slug) as Promise<CreatorResource[]>,
      ])

    const pathways  = pathwaysResult.status === 'fulfilled'  ? pathwaysResult.value  : []
    const events    = eventsResult.status === 'fulfilled'    ? eventsResult.value    : []
    const members   = membersResult.status === 'fulfilled'   ? membersResult.value   : []
    const invites   = invitesResult.status === 'fulfilled'   ? invitesResult.value   : []
    const requests  = requestsResult.status === 'fulfilled'  ? requestsResult.value  : []
    const resources = resourcesResult.status === 'fulfilled' ? resourcesResult.value : []

    const now = Date.now()

    liteData.pathwayCounts = {
      published:  pathways.filter(p => p.status === 'active').length,
      comingSoon: pathways.filter(p => p.status === 'coming_soon').length,
      drafts:     pathways.filter(p => p.status === 'draft').length,
      archived:   pathways.filter(p => p.status === 'archived').length,
    }

    const pathwayShape = (p: CreatorPathway) => ({
      id:          p.id,
      slug:        p.slug,
      title:       p.title,
      status:      p.status,
      access_type: p.access_type,
      price_cents: p.price_cents ?? null,
      currency:    p.currency ?? null,
    })

    liteData.publishedPathways = pathways.filter(p => p.status === 'active').map(pathwayShape)
    liteData.allPathways = pathways.map(pathwayShape)

    liteData.upcomingGatherings = events
      .filter(e => e.status === 'active' && new Date(e.starts_at).getTime() >= now)
      .sort((a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime())
      .slice(0, 5)
      .map(e => ({
        id:               e.id,
        title:            e.title,
        starts_at:        e.starts_at,
        booked_count:     e.booked_count,
        capacity:         e.capacity,
        requires_booking: e.requires_booking,
        is_published:     e.is_published,
      }))

    liteData.memberCount = members.filter(m => m.space_role === 'learner').length
    liteData.leaderCount = members.filter(m => m.space_role === 'creator' || m.space_role === 'moderator').length

    liteData.members = members.map(m => ({ id: m.id, display_name: m.display_name }))

    liteData.invitations = invites.map(i => ({
      id:         i.id,
      email:      i.email,
      name:       i.name,
      role:       i.role,
      token:      i.token,
      created_at: i.created_at,
    }))

    liteData.accessRequests = requests.map(r => ({
      id:                  r.id,
      user_display_name:   r.user_display_name,
      user_email:          r.user_email,
      created_at:          r.created_at,
      status:              r.status,
    }))

    liteData.pendingInvites  = invites.length
    liteData.pendingRequests = requests.filter(r => r.status === 'pending').length

    // Count published resources (CreatorResource has status field)
    liteData.resourceCount = resources.filter(r => r.status === 'published').length
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
