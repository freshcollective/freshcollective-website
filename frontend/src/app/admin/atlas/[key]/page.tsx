import { notFound } from 'next/navigation'
import { getAdminLocation } from '@/lib/serverApi'
import type { LocationDetail } from '@/lib/atlas/types'
import LocationDetailClient from './LocationDetailClient'

interface PageProps {
  params: Promise<{ key: string }>
}

/**
 * Detail page for one Location. Server-fetches the Location and hands off
 * to the client component for editing. Classification / recommendation
 * metadata is no longer surfaced here — see Atlas v1.1 refinements.
 */
export default async function LocationDetailPage({ params }: PageProps) {
  const { key } = await params
  const location: LocationDetail | null = await getAdminLocation(key)
  if (!location) notFound()
  return <LocationDetailClient initialLocation={location} />
}
