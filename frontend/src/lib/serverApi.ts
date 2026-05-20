import { cache } from 'react'
import { cookies } from 'next/headers'
import { apiUrl } from './api'
import { SESSION_COOKIE } from './session'
import type { CreatorBillingResponse, PublicSpaceCard, SpaceSummary } from '@/types/platform'

export const ACTIVE_SPACE_COOKIE = 'fc_creator_space'

async function fetchWithSession(path: string): Promise<Response> {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value ?? ''
  return fetch(apiUrl(path), {
    headers: { Cookie: `${SESSION_COOKIE}=${token}` },
    next: { revalidate: 0 },
  })
}

export const getPublicSpaces = cache(async (): Promise<PublicSpaceCard[]> => {
  try {
    const res = await fetch(apiUrl('/api/public/spaces'), { next: { revalidate: 60 } })
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

export const getCommunityFeed = cache(async (spaceSlug: string) => {
  const res = await fetchWithSession(`/api/spaces/${spaceSlug}/community`)
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

export const getSpaceEvents = cache(async (slug: string) => {
  const res = await fetchWithSession(`/api/spaces/${slug}/events`)
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

export const getCreatorPathways = cache(async (slug: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/pathways`)
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

export const getCreatorEvents = cache(async (slug: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/events`)
  if (!res.ok) return []
  return res.json()
})

export const getCreatorEvent = cache(async (slug: string, eventId: string) => {
  const res = await fetchWithSession(`/api/creator/spaces/${slug}/events/${eventId}`)
  if (!res.ok) return null
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

export const getCreatorBilling = cache(async (): Promise<CreatorBillingResponse | null> => {
  try {
    const res = await fetchWithSession('/api/creator/billing')
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
})
