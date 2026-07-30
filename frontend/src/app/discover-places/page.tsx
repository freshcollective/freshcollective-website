import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import PageHero from '@/components/layout/PageHero'
import SiteShell from '@/components/layout/SiteShell'
import { isDiscoveryPillarEnabled } from '@/lib/featureFlags'
import DiscoverPlacesPrototype from './_prototype/DiscoverPlacesPrototype'

export const metadata: Metadata = {
  title: 'Discover Places · Fresh Collective',
  description:
    'The places where our communities are gathering, learning and belonging.',
}

/**
 * Discover Places — currently hosting a design prototype behind
 * the pillar's shared PageHero. The hero is authored at the page
 * level so the prototype (and, later, the real Phase 1 surface)
 * only owns its own content, not the destination framing.
 *
 * The flag gate is unchanged: when
 * NEXT_PUBLIC_DISCOVERY_PILLAR_ENABLED is off, this route 404s.
 *
 * See docs/foundations/discovery-connection-belonging-v1.1.md.
 */
export default function DiscoverPlacesPage() {
  if (!isDiscoveryPillarEnabled()) notFound()

  return (
    <SiteShell>
      <PageHero
        title="Where communities are growing"
        supportingCopy="The places where our communities are gathering, learning and belonging."
      />
      <DiscoverPlacesPrototype />
    </SiteShell>
  )
}
