import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import Container from '@/components/layout/Container'
import SiteShell from '@/components/layout/SiteShell'
import { isDiscoveryPillarEnabled } from '@/lib/featureFlags'

export const metadata: Metadata = {
  title: 'Discover Places · Fresh Collective',
  description:
    'The cities, towns and regions where Fresh Collective is quietly growing.',
}

/**
 * Discover Places — Phase 0 placeholder.
 *
 * The room exists; the world it will one day show is still forming.
 * This page is deliberately spare. It is not a software placeholder —
 * there is nothing "coming soon" or "under construction" here. It is
 * an empty room in a living world, calm and consistent with the
 * pillar's philosophy. See
 * ``docs/foundations/discovery-connection-belonging-v1.1.md``.
 */
export default function DiscoverPlacesPage() {
  if (!isDiscoveryPillarEnabled()) notFound()

  return (
    <SiteShell>
      <Container className="py-24 md:py-32">
        <div className="mx-auto max-w-xl">
          <h1 className="mb-6 font-serif text-3xl text-navy-900 md:text-4xl">
            Discover Places
          </h1>
          <p className="mb-6 font-serif text-lg italic leading-relaxed text-navy-600">
            This part of the world is still taking shape.
          </p>
          <p className="text-[15px] leading-relaxed text-navy-500">
            Soon you&rsquo;ll be able to discover the cities, towns and
            regions where Fresh Collective is quietly growing.
          </p>
        </div>
      </Container>
    </SiteShell>
  )
}
