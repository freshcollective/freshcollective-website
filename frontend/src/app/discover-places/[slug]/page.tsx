import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import SiteShell from '@/components/layout/SiteShell'
import { isDiscoveryPillarEnabled } from '@/lib/featureFlags'
import { getViewerCollectives } from '@/lib/joinedCollectives'
import { getPublicPlace } from '@/lib/serverApi'
import type { PublicPlaceDetail } from '@/lib/physicalLocations/types'
import PlaceDetailView from './PlaceDetailView'

interface PageProps {
  params: Promise<{ slug: string }>
}

export async function generateMetadata(
  { params }: PageProps,
): Promise<Metadata> {
  const { slug } = await params
  const place = (await getPublicPlace(slug)) as PublicPlaceDetail | null
  if (!place) {
    return { title: 'Place · Fresh Collective' }
  }
  return {
    title: `${place.name} · Fresh Collective`,
    description:
      place.blurb
      ?? `Fresh Collective communities in ${place.name}.`,
  }
}

/**
 * Discover Places — location detail.
 *
 * Answers "what communities and opportunities are available in this
 * area?" for a single active Physical Location. Sourced from
 * ``GET /api/places/{slug}``; draft / hidden / archived locations
 * 404 here.
 *
 * The location's own artwork lives only in the hero. Collectives
 * listed underneath keep their own artwork and identity — they never
 * inherit the location's visual identity.
 *
 * Membership is resolved here rather than in the view: the cards are
 * the same ``CollectiveCard`` Explore uses, and a member who finds
 * their own Collective through a Place should be taken into it, not
 * shown the joining page. ``getViewerCollectives`` makes no request for a
 * signed-out visitor, so public Place browsing costs nothing extra.
 * Gathering and Series links below are unaffected — those are
 * destinations in their own right, not doorways into a Collective.
 */
export default async function PlaceDetailPage({ params }: PageProps) {
  if (!isDiscoveryPillarEnabled()) notFound()
  const { slug } = await params
  const [place, viewer] = await Promise.all([
    getPublicPlace(slug) as Promise<PublicPlaceDetail | null>,
    getViewerCollectives(),
  ])
  if (!place) notFound()
  return (
    <SiteShell>
      <PlaceDetailView
        place={place}
        joinedSlugs={viewer.joinedSlugs}
        isLoggedIn={viewer.isLoggedIn}
      />
    </SiteShell>
  )
}
