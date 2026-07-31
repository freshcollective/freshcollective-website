import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import PageHero from '@/components/layout/PageHero'
import SiteShell from '@/components/layout/SiteShell'
import { isDiscoveryPillarEnabled } from '@/lib/featureFlags'
import { getPublicPlaces } from '@/lib/serverApi'
import type { PublicPlaceSummary } from '@/lib/physicalLocations/types'
import DiscoverPlacesLive from './DiscoverPlacesLive'

export const metadata: Metadata = {
  title: 'Discover Places · Fresh Collective',
  description:
    'The places where our communities are gathering, learning and belonging.',
}

/**
 * Discover Places — the real member-facing surface, backed by the
 * curated Physical Locations catalogue (``/api/places``). Only
 * ``active`` Locations reach here; the API server-side filters out
 * draft, hidden and archived rows.
 *
 * The design prototype used to render here; it now lives under
 * ``_prototype/`` for isolated design review only and is not
 * mounted by any route.
 *
 * The flag gate is unchanged: when
 * NEXT_PUBLIC_DISCOVERY_PILLAR_ENABLED is off, this route 404s.
 *
 * See docs/foundations/discovery-connection-belonging-v1.1.md.
 */
export default async function DiscoverPlacesPage() {
  if (!isDiscoveryPillarEnabled()) notFound()

  const places = (await getPublicPlaces()) as PublicPlaceSummary[]

  return (
    <SiteShell>
      <PageHero
        title="Where communities are growing"
        supportingCopy="The places where our communities are gathering, learning and belonging."
      />
      <DiscoverPlacesLive places={places} />
    </SiteShell>
  )
}
