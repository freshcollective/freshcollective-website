import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import Container from '@/components/layout/Container'
import PageHero from '@/components/layout/PageHero'
import SiteShell from '@/components/layout/SiteShell'
import { isDiscoveryPillarEnabled } from '@/lib/featureFlags'

export const metadata: Metadata = {
  title: 'Ways to Connect · Fresh Collective',
  description:
    'How meaningful connection grows through Fresh Collective — shared experiences, gatherings, and journeys.',
}

/**
 * Ways to Connect — Phase 0 placeholder inside the shared discovery
 * hero family. The hero establishes the destination; the placeholder
 * sentence beneath it is honest about the surface still opening.
 * See docs/foundations/discovery-connection-belonging-v1.1.md.
 */
export default function WaysToConnectPage() {
  if (!isDiscoveryPillarEnabled()) notFound()

  return (
    <SiteShell>
      <PageHero
        title="Ways to Connect"
        supportingCopy="Meaningful connection grows through shared experiences."
      />

      {/* Placeholder body — deliberately quiet. Replaced by the real
          Ways to Connect experience in a later stage. */}
      <Container className="py-16 md:py-20">
        <div className="mx-auto max-w-xl">
          <p className="font-serif text-lg italic leading-relaxed text-navy-600">
            This part of the world will open as our communities
            continue to grow.
          </p>
        </div>
      </Container>
    </SiteShell>
  )
}
