import { cache } from 'react'
import { cookies } from 'next/headers'
import { apiUrl } from './api'
import { SESSION_COOKIE } from './session'
import type { AccessPassAdminSummary, AccessPassSummary, AccessRequest, ActivityListResponse, AggregatedResourcesResponse, CreatorBillingResponse, CreatorMemberDetail, InviteLookupResponse, ManualMember, MemberBookingItem, PublicSpaceCard, SpaceAccessStatus, SpaceSummary } from '@/types/platform'

// Re-export so existing callers keep working. The canonical definition
// lives in ``@/lib/activeSpaceCookie`` because the proxy middleware also
// needs it and cannot import from a module that pulls in ``next/headers``.
import { ACTIVE_SPACE_COOKIE } from './activeSpaceCookie'
export { ACTIVE_SPACE_COOKIE }

async function fetchWithSession(path: string): Promise<Response> {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value ?? ''
  return fetch(apiUrl(path), {
    headers: { Cookie: `${SESSION_COOKIE}=${token}` },
    next: { revalidate: 0 },
  })
}

/** Exported alias for pages that need to hit an endpoint outside the
 *  helpers below (e.g. the manual-releases page). Same session cookie
 *  wiring — do not re-implement this anywhere else. */
export async function serverFetch(path: string): Promise<Response> {
  return fetchWithSession(path)
}


// ---------------------------------------------------------------------------
// Conversation Channels
// ---------------------------------------------------------------------------

export interface ChannelSummaryLite {
  id: string
  slug: string
  name: string
  description: string | null
  /** Always populated by the server — either the type-driven default
   *  icon (🌱🌍🛤📅🔒💬) or a stored override. */
  icon_emoji: string | null
  channel_type: string
  /** Frontend groups channels under this heading. `null` means the
   *  channel belongs in the un-headed system row at the very top. */
  group_label: string | null
  is_default: boolean
  is_system: boolean
  is_archived: boolean
  show_in_navigation: boolean
  member_posting_allowed: boolean
  comments_allowed: boolean
  polls_allowed: boolean
  scheduling_allowed: boolean
  pathway_id: string | null
  gathering_id: string | null
}

export const getMemberChannels = cache(async (spaceSlug: string): Promise<ChannelSummaryLite[]> => {
  const res = await fetchWithSession(`/api/spaces/${spaceSlug}/channels`)
  if (!res.ok) return []
  return res.json()
})

export interface ChannelManageDetail extends ChannelSummaryLite {
  post_count: number
  private_member_count: number
  created_at: string
  updated_at: string
}

export const getCreatorChannels = cache(async (spaceSlug: string): Promise<ChannelManageDetail[]> => {
  const res = await fetchWithSession(`/api/creator/spaces/${spaceSlug}/channels`)
  if (!res.ok) return []
  return res.json()
})

export const getPublicSpaces = cache(async (): Promise<PublicSpaceCard[]> => {
  try {
    const res = await fetch(apiUrl('/api/public/spaces'), { cache: 'no-store' })
    if (!res.ok) return []
    return res.json()
  } catch {
    return []
  }
})

export const getSpace = cache(async (slug: string) => {
  const res = await fetchWithSession(`/api/spaces/${slug}`)
  if (!res.ok) return null
  return res.json()
})

export const getSpacePathways = cache(async (slug: string) => {
  const res = await fetchWithSession(`/api/spaces/${slug}/pathways`)
  if (!res.ok) return []
  return res.json()
})

export const getPathway = cache(async (spaceSlug: string, pathwaySlug: string) => {
  const res = await fetchWithSession(`/api/spaces/${spaceSlug}/pathways/${pathwaySlug}`)
  if (!res.ok) return null
  return res.json()
})

export const getPathwayOverview = cache(async (spaceSlug: string, pathwaySlug: string) => {
  const res = await fetchWithSession(`/api/spaces/${spaceSlug}/pathways/${pathwaySlug}/overview`)
  if (!res.ok) return null
  return res.json()
})

export const getStep = cache(async (spaceSlug: string, pathwaySlug: string, stepSlug: string) => {
  const res = await fetchWithSession(
    `/api/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps/${stepSlug}`,
  )
  if (!res.ok) return null
  return res.json()
})

export const getSteps = cache(async (spaceSlug: string, pathwaySlug: string) => {
  const res = await fetchWithSession(`/api/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps`)
  if (!res.ok) return []
  return res.json()
})

export const getSpaceMembers = cache(async (spaceSlug: string) => {
  const res = await fetchWithSession(`/api/spaces/${spaceSlug}/members`)
  if (!res.ok) return []
  return res.json()
})

export const getPublicProfile = cache(async (userId: string) => {
  const res = await fetchWithSession(`/api/profile/${userId}`)
  if (!res.ok) return null
  return res.json()
})

export const getCommunityFeed = cache(async (
  spaceSlug: string,
  channelSlug?: string,
) => {
  const suffix = channelSlug ? `?channel=${encodeURIComponent(channelSlug)}` : ''
  const res = await fetchWithSession(`/api/spaces/${spaceSlug}/community${suffix}`)
  if (!res.ok) return []
  return res.json()
})

export const getCommunityPost = cache(async (spaceSlug: string, postId: string) => {
  const res = await fetchWithSession(`/api/spaces/${spaceSlug}/community/${postId}`)
  if (!res.ok) return null
  return res.json()
})

export const getSpaceEvent = cache(async (spaceSlug: string, eventId: string) => {
  const res = await fetchWithSession(`/api/spaces/${spaceSlug}/events/${eventId}`)
  if (!res.ok) return null
  return res.json()
})

export const getSpacePathwaysProgress = cache(async (slug: string) => {
  const res = await fetchWithSession(`/api/spaces/${slug}/pathways-progress`)
  if (!res.ok) return []
  return res.json()
})

export const getSpaceEvents = cache(async (
  slug: string,
  scope?: 'upcoming' | 'archive',
) => {
  const suffix = scope ? `?scope=${scope}` : ''
  const res = await fetchWithSession(`/api/spaces/${slug}/events${suffix}`)
  if (!res.ok) return []
  return res.json()
})

export const getContinue = cache(async () => {
  const res = await fetchWithSession('/api/me/continue')
  if (!res.ok) return null
  return res.json()
})

export const getMe = cache(async () => {
  const res = await fetchWithSession('/api/auth/me')
  if (!res.ok) return null
  return res.json()
})

export const getMyMemberships = cache(async () => {
  const res = await fetchWithSession('/api/auth/me/memberships')
  if (!res.ok) return []
  return res.json()
})

// ---------------------------------------------------------------------------
// Creator Studio
// ---------------------------------------------------------------------------

export const getCreatorSpaces = cache(async () => {
  const res = await fetchWithSession('/api/creator/spaces')
  if (!res.ok) return []
  return res.json()
})

// ---------------------------------------------------------------------------
// The Atlas — admin surface for curated Locations (Atlas v1.1, Ch. 9-12)
// ---------------------------------------------------------------------------

export const getAdminLocations = cache(async () => {
  const res = await fetchWithSession('/api/admin/atlas/locations')
  if (!res.ok) return []
  return res.json()
})

export const getAdminLocation = cache(async (key: string) => {
  const res = await fetchWithSession(`/api/admin/atlas/locations/${key}`)
  if (!res.ok) return null
  return res.json()
})

// ---------------------------------------------------------------------------
// Mother World — platform-wide snapshot used by the World Management overview
// page. Mirrors the shape of `AdminPlatformOverview` in backend/schemas.py.
// ---------------------------------------------------------------------------

export interface MotherWorldMoment {
  kind: 'collective' | 'creator' | 'transaction' | 'gathering' | 'signup'
  message: string
  when: string
  href: string | null
}

export interface MotherWorldHealth {
  platform_ok: boolean
  stripe_ok: boolean
  webhook_configured: boolean
  standalone_gathering_sales_enabled: boolean
  stripe_mode: 'test' | 'live' | string
  last_backup_at: string | null
}

export interface MotherWorldOverview {
  total_collectives: number
  active_collectives: number
  draft_collectives: number
  archived_collectives: number
  total_users: number
  admin_users: number
  creator_users: number
  member_users: number
  pending_access_requests: number
  pending_invitations: number
  total_gross_cents: number
  succeeded_transactions: number
  upcoming_gatherings: number
  total_gross_cents_today: number
  total_gross_cents_7d: number
  failed_transactions_7d: number
  recent_moments: MotherWorldMoment[]
  world_health: MotherWorldHealth
}

export const getMotherWorldOverview = cache(async (): Promise<MotherWorldOverview | null> => {
  const res = await fetchWithSession('/api/admin/platform/overview')
  if (!res.ok) return null
  return res.json()
})

// ---------------------------------------------------------------------------
// Platform Artwork — shared interface assets owned by the platform itself
// (not by any Atlas Location). Managed from /admin/settings/artwork.
// ---------------------------------------------------------------------------

export interface PlatformArtworkItem {
  key: string
  title: string
  description: string
  image_url: string | null
  thumbnail_url: string | null
  updated_at: string | null
}

export interface PublicPlatformArtwork {
  key: string
  image_url: string | null
  thumbnail_url: string | null
}

export const getAdminPlatformArtwork = cache(async (): Promise<PlatformArtworkItem[]> => {
  const res = await fetchWithSession('/api/admin/platform-artwork')
  if (!res.ok) return []
  return res.json()
})

export const getPublicPlatformArtwork = cache(async (): Promise<PublicPlatformArtwork[]> => {
  const res = await fetchWithSession('/api/platform-artwork')
  if (!res.ok) return []
  return res.json()
})

// ---------------------------------------------------------------------------
// Admin Collectives — Gallery/List redesign feed
// ---------------------------------------------------------------------------

export type AdminCollectiveHealth = 'healthy' | 'quiet' | 'needs_attention'

export interface AdminCollectiveRow {
  id: string
  name: string
  slug: string
  status: 'active' | 'draft' | 'archived' | string
  is_public: boolean
  has_paid_internal_content: boolean
  creator_id: string | null
  creator_name: string | null
  creator_email: string | null
  member_count: number
  pathway_count: number
  gathering_count: number
  resource_count: number
  created_at: string
  updated_at: string
  cover_image_url: string | null
  location_id: string | null
  location_name: string | null
  // Curated hero artwork of the Atlas Location the collective lives in.
  // Same source the member-facing CollectiveIdentityHeader uses. This is
  // the collective's true visual identity under Atlas v1.2.
  location_hero_artwork_url: string | null
  last_activity_at: string | null
  next_gathering_at: string | null
  new_members_7d: number
  health: AdminCollectiveHealth
  activity_phrase: string
}

export const getAdminCollectives = cache(async (): Promise<AdminCollectiveRow[]> => {
  const res = await fetchWithSession('/api/admin/platform/collectives')
  if (!res.ok) return []
  return res.json()
})

// ---------------------------------------------------------------------------
// Admin Creators — Gallery/List redesign feed
// ---------------------------------------------------------------------------

export type AdminCreatorHealth = 'flourishing' | 'new' | 'quiet' | 'needs_support'

export interface AdminCreatorCollectiveChip {
  id: string
  slug: string
  name: string
  location_name: string | null
  location_hero_artwork_url: string | null
}

export interface AdminCreatorRow {
  id: string
  name: string | null
  email: string
  role: string
  created_at: string
  collective_count: number
  published_collective_count: number
  draft_collective_count: number
  plan_name: string
  subscription_status: string
  avatar_url: string | null
  collectives: AdminCreatorCollectiveChip[]
  total_members_reached: number
  last_activity_at: string | null
  next_gathering_at: string | null
  new_members_30d: number
  health: AdminCreatorHealth
  activity_phrase: string
}

export const getAdminCreators = cache(async (): Promise<AdminCreatorRow[]> => {
  const res = await fetchWithSession('/api/admin/platform/creators')
  if (!res.ok) return []
  return res.json()
})

// ---------------------------------------------------------------------------
// Build Your Collective — the guided creator ritual (Atlas v1.2, Chapter 4)
// ---------------------------------------------------------------------------

export const getBuildYourCollectiveOptions = cache(async () => {
  const res = await fetchWithSession('/api/creator/build-your-collective/options')
  if (!res.ok) return null
  return res.json()
})

export const getBuildYourCollectiveDraft = cache(async () => {
  const res = await fetchWithSession('/api/creator/build-your-collective/draft')
  if (!res.ok) return null
  const data = await res.json()
  return data // may be null (no draft yet) or { data: {...} }
})

export const getActiveCreatorSpace = cache(async (): Promise<SpaceSummary | null> => {
  const spaces: SpaceSummary[] = await getCreatorSpaces()
  if (!spaces.length) return null
  const cookieStore = await cookies()
  const slug = cookieStore.get(ACTIVE_SPACE_COOKIE)?.value
  if (slug) {
    const found = spaces.find(s => s.slug === slug)
    if (found) return found
  }
  return spaces[0]
})

export const getCreatorSpace = cache(async (slug: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}`)
  if (!res.ok) return null
  return res.json()
})

/**
 * Header context for the shared collective page header.
 *
 * Resolves the active collective from the same authoritative source
 * used everywhere else (the middleware-synced ``fc_creator_space``
 * cookie) and returns the identity data the header needs — plus the
 * summary so pages can re-use the slug + status without a second
 * fetch. Returns null when the creator has no collectives yet.
 *
 * The header MUST render from this same object as the page itself,
 * otherwise the banner and the page data can drift out of sync.
 */
export const getActiveCollectiveHeader = cache(async () => {
  const space = await getActiveCreatorSpace()
  if (!space) return null
  const detail = await getCreatorSpace(space.slug) as import('@/types/platform').CreatorSpaceDetail | null
  return {
    space,
    detail,
    // Convenience shortcuts for the header component's props.
    name: space.name,
    status: space.status,
    location: detail?.location ?? null,
    coverImageUrl: detail?.cover_image_url ?? null,
  }
})

export const getCreatorPathways = cache(async (slug: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/pathways`)
  if (!res.ok) return []
  return res.json()
})

export const getSpaceResources = cache(async (slug: string): Promise<AggregatedResourcesResponse> => {
  const res = await fetchWithSession(`/api/spaces/${slug}/resources`)
  if (!res.ok) return { standalone_resources: [], pathway_resource_groups: [] }
  return res.json()
})

export const getCreatorResources = cache(async (slug: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/resources`)
  if (!res.ok) return []
  return res.json()
})

export const getCreatorPathway = cache(async (slug: string, pathwaySlug: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/pathways/${pathwaySlug}`)
  if (!res.ok) return null
  return res.json()
})

export const getCreatorSteps = cache(async (slug: string, pathwaySlug: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/pathways/${pathwaySlug}/steps`)
  if (!res.ok) return []
  return res.json()
})

export const getCreatorSections = cache(async (slug: string, pathwaySlug: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/pathways/${pathwaySlug}/sections`)
  if (!res.ok) return []
  return res.json()
})

export const getCreatorStep = cache(async (slug: string, pathwaySlug: string, stepSlug: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/pathways/${pathwaySlug}/steps/${stepSlug}`)
  if (!res.ok) return null
  return res.json()
})

export const getCreatorEvents = cache(async (
  slug: string,
  scope?: 'upcoming' | 'archive',
) => {
  const suffix = scope ? `?scope=${scope}` : ''
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/events${suffix}`)
  if (!res.ok) return []
  return res.json()
})

export const getCreatorEvent = cache(async (slug: string, eventId: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/events/${eventId}`)
  if (!res.ok) return null
  return res.json()
})

export const getCreatorEventBookings = cache(async (slug: string, eventId: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/events/${eventId}/bookings`)
  if (!res.ok) return []
  return res.json()
})

export const getCreatorMembers = cache(async (slug: string): Promise<CreatorMemberDetail[]> => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/members`)
  if (!res.ok) return []
  return res.json()
})

export const getMemberBookings = cache(async (slug: string, userId: string): Promise<MemberBookingItem[]> => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/members/${userId}/bookings`)
  if (!res.ok) return []
  return res.json()
})

export const getManualMembers = cache(async (slug: string): Promise<ManualMember[]> => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/manual-members`)
  if (!res.ok) return []
  return res.json()
})

export const getCreatorInvitations = cache(async (slug: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/invitations`)
  if (!res.ok) return []
  return res.json()
})

export const getCreatorPosts = cache(async (slug: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/community`)
  if (!res.ok) return []
  return res.json()
})

export const getCreatorMedia = cache(async (slug: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/media`)
  if (!res.ok) return []
  return res.json()
})

export const getCreatorStepResources = cache(async (slug: string, pathwaySlug: string, stepSlug: string) => {
  const res = await fetchWithSession(
    `/api/creator/spaces/${slug}/pathways/${pathwaySlug}/steps/${stepSlug}/resources`,
  )
  if (!res.ok) return []
  return res.json()
})

export const getStepResources = cache(async (spaceSlug: string, pathwaySlug: string, stepSlug: string) => {
  const res = await fetchWithSession(
    `/api/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps/${stepSlug}/resources`,
  )
  if (!res.ok) return []
  return res.json()
})

export const getCreatorStepBlocks = cache(async (slug: string, pathwaySlug: string, stepSlug: string) => {
  const res = await fetchWithSession(
    `/api/creator/spaces/${slug}/pathways/${pathwaySlug}/steps/${stepSlug}/blocks`,
  )
  if (!res.ok) return []
  return res.json()
})

export const getStepBlocks = cache(async (spaceSlug: string, pathwaySlug: string, stepSlug: string) => {
  const res = await fetchWithSession(
    `/api/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps/${stepSlug}/blocks`,
  )
  if (!res.ok) return []
  return res.json()
})

export const getStepComments = cache(async (spaceSlug: string, pathwaySlug: string, stepSlug: string) => {
  const res = await fetchWithSession(
    `/api/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps/${stepSlug}/comments`,
  )
  if (!res.ok) return []
  return res.json()
})

export const getCreatorPathwayAboutBlocks = cache(async (spaceSlug: string, pathwaySlug: string) => {
  const res = await fetchWithSession(
    `/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/about-blocks`,
  )
  if (!res.ok) return []
  return res.json()
})

export const getPathwayAboutBlocks = cache(async (spaceSlug: string, pathwaySlug: string) => {
  const res = await fetchWithSession(
    `/api/spaces/${spaceSlug}/pathways/${pathwaySlug}/about-blocks`,
  )
  if (!res.ok) return []
  return res.json()
})

export const getMySpaceAccess = cache(async (slug: string): Promise<SpaceAccessStatus | null> => {
  try {
    const res = await fetchWithSession(`/api/spaces/${slug}/my-access`)
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
})

export const getInviteByToken = cache(async (token: string): Promise<InviteLookupResponse | null> => {
  try {
    const res = await fetch(apiUrl(`/api/invites/${token}`), { next: { revalidate: 0 } })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
})

export const getCreatorAccessRequests = cache(async (slug: string): Promise<AccessRequest[]> => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/access-requests`)
  if (!res.ok) return []
  return res.json()
})

export const getCreatorPasses = cache(async (slug: string): Promise<AccessPassAdminSummary[]> => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/passes`)
  if (!res.ok) return []
  return res.json()
})

export const getMyPasses = cache(async (slug: string): Promise<AccessPassSummary[]> => {
  const res = await fetchWithSession(`/api/spaces/${slug}/my-passes`)
  if (!res.ok) return []
  return res.json()
})

export const getCreatorBilling = cache(async (): Promise<CreatorBillingResponse | null> => {
  try {
    const res = await fetchWithSession('/api/creator/billing')
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
})


// ---------------------------------------------------------------------------
// Activity Engine — "Recent Moments" panels
//
// Recipient scope is always the current caller. ``collectiveId`` narrows
// the result to a single collective, so the same endpoint powers both
// the Your-World feed ("across your world") and each collective's
// sidebar panel ("in this place").
//
// ``recent_moments=true`` restricts the result to the curated Recent
// Moments whitelist on the backend (see ``RECENT_MOMENTS`` in
// ``app.models.activity``). Attention-required and history-only events
// are excluded so this helper is safe to call from any RM surface.
// ---------------------------------------------------------------------------

export const getRecentActivities = cache(async (
  limit: number,
  collectiveId?: string,
): Promise<ActivityListResponse> => {
  const params = new URLSearchParams({
    limit: String(limit),
    recent_moments: 'true',
  })
  if (collectiveId) params.set('collective_id', collectiveId)
  try {
    const res = await fetchWithSession(`/api/activities?${params.toString()}`)
    if (!res.ok) return { activities: [], next_before: null }
    return (await res.json()) as ActivityListResponse
  } catch {
    return { activities: [], next_before: null }
  }
})
