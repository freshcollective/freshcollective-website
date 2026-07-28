import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import Container from '@/components/layout/Container'
import SiteShell from '@/components/layout/SiteShell'
import { isDiscoveryPillarEnabled } from '@/lib/featureFlags'

export const metadata: Metadata = {
  title: 'Ways to Connect · Fresh Collective',
  description:
    'How meaningful connection grows through Fresh Collective — shared experiences, gatherings, and journeys.',
}

/**
 * Ways to Connect — Phase 0 placeholder.
 *
 * The pillar's connective tissue — the surface where members find
 * one another and choose to journey together — is not yet ready to
 * open. Rather than announcing that in software terms, the page
 * greets visitors with a quiet, honest sentence about how connection
 * grows here. See
 * ``docs/foundations/discovery-connection-belonging-v1.1.md``.
 */
export default function WaysToConnectPage() {
  if (!isDiscoveryPillarEnabled()) notFound()

  return (
    <SiteShell>
      <Container className="py-24 md:py-32">
        <div className="mx-auto max-w-xl">
          <h1 className="mb-6 font-serif text-3xl text-navy-900 md:text-4xl">
            Ways to Connect
          </h1>
          <p className="mb-6 font-serif text-lg italic leading-relaxed text-navy-600">
            Meaningful connection grows through shared experiences.
          </p>
          <p className="text-[15px] leading-relaxed text-navy-500">
            This part of the world will open as our communities
            continue to grow.
          </p>
        </div>
      </Container>
    </SiteShell>
  )
}
