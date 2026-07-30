import { notFound } from 'next/navigation'
import { getAdminPhysicalLocation } from '@/lib/serverApi'
import type { PhysicalLocationDetail } from '@/lib/physicalLocations/types'
import PhysicalLocationClient from './PhysicalLocationClient'

interface PageProps {
  params: Promise<{ slug: string }>
}

/**
 * Detail page for one Physical Location. Server-fetches the record
 * and hands off to the client component for editing.
 */
export default async function PhysicalLocationDetailPage({ params }: PageProps) {
  const { slug } = await params
  const location: PhysicalLocationDetail | null = await getAdminPhysicalLocation(slug)
  if (!location) notFound()
  return <PhysicalLocationClient initialLocation={location} />
}
