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
