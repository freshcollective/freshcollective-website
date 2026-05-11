import { cache } from 'react'
import { cookies } from 'next/headers'
import { apiUrl } from './api'
import { SESSION_COOKIE } from './session'

async function fetchWithSession(path: string): Promise<Response> {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value ?? ''
  return fetch(apiUrl(path), {
    headers: { Cookie: `${SESSION_COOKIE}=${token}` },
    next: { revalidate: 0 },
  })
}

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
