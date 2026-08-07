import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import PageHero from '@/components/layout/PageHero'
import SiteShell from '@/components/layout/SiteShell'
import { isDiscoveryPillarEnabled } from '@/lib/featureFlags'
import WaysToConnectPrototype from './_prototype/WaysToConnectPrototype'

export const metadata: Metadata = {
  title: 'Ways to Connect · Fresh Collective',
  description:
    'A good host introducing two people at a gathering. Fresh Collective reveals the connections that already exist.',
}

/**
 * Ways to Connect — currently hosting a design prototype behind
 * the pillar's shared PageHero. The hero is authored at the page
 * level so the prototype only owns its own interactive content.
 *
 * The flag gate is unchanged: when
 * NEXT_PUBLIC_DISCOVERY_PILLAR_ENABLED is off, this route 404s.
 *
 * See docs/foundations/discovery-connection-belonging-ways-to-connect.md.
 */
export default function WaysToConnectPage() {
  if (!isDiscoveryPillarEnabled()) notFound()

  return (
    <SiteShell>
      <PageHero
        title="Ways to Connect"
        supportingCopy="Meaningful connection grows through shared experiences. Fresh Collective reveals the ones that already exist — nothing more."
      />
      <WaysToConnectPrototype />
    </SiteShell>
  )
}
