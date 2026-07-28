import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import SiteShell from '@/components/layout/SiteShell'
import { isDiscoveryPillarEnabled } from '@/lib/featureFlags'
import DiscoverPlacesPrototype from './_prototype/DiscoverPlacesPrototype'

export const metadata: Metadata = {
  title: 'Discover Places · Fresh Collective',
  description:
    'The cities, towns and regions where Fresh Collective is quietly growing.',
}

/**
 * Discover Places — currently hosting a design prototype.
 *
 * The pillar's flag still gates access: when
 * NEXT_PUBLIC_DISCOVERY_PILLAR_ENABLED is off, this route 404s and
 * ordinary users cannot reach it. When the flag is on, we render
 * ``_prototype/DiscoverPlacesPrototype`` — a client-side visual
 * prototype fed by local mock data, used to evaluate the browsing
 * feeling before Phase 1 design starts.
 *
 * Nothing here talks to /api/places or the database. When the real
 * Phase 1 page ships, replace the prototype mount with the
 * production experience and delete ``./_prototype`` in full.
 *
 * See docs/foundations/discovery-connection-belonging-v1.1.md.
 */
export default function DiscoverPlacesPage() {
  if (!isDiscoveryPillarEnabled()) notFound()

  return (
    <SiteShell>
      <DiscoverPlacesPrototype />
    </SiteShell>
  )
}
