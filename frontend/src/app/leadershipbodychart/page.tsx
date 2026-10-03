/**
 * /leadershipbodychart — preserved legacy URL.
 *
 * This exact path is printed in material associated with the Natural
 * Leader book, so it must keep resolving after freshcollective.au stops
 * pointing at Wix. It is deliberately NOT a redirect: the URL itself is
 * the thing being preserved.
 *
 * The chart is Neutrino's, rendered through the ordinary embed path —
 * ``EmbedRenderer`` builds a sandboxed iframe and nothing of Neutrino's
 * own loader script or style block is used. ``neutrinoplatform.com`` was
 * already an allowlisted provider and already in CSP ``frame-src``, so
 * this route needed no security relaxation of any kind.
 *
 * Neutrino captures the visitor's email itself. The optional
 * Flodesk/webhook integration is not a launch dependency.
 *
 * Until ``NEUTRINO_CHART_EMBED_URL`` is configured this route 404s
 * rather than rendering a chartless shell. A 200 with no chart on a URL
 * printed in a book is worse than a 404: it looks like the page works.
 * See ``lib/legacyRoutes.ts``.
 */

import type { Metadata } from 'next'
import { notFound } from 'next/navigation'

import EmbedRenderer from '@/components/EmbedRenderer'
import Container from '@/components/layout/Container'
import SiteShell from '@/components/layout/SiteShell'
import { resolveChartEmbed } from '@/lib/legacyRoutes'

/**
 * Read the embed configuration per request, not at build time.
 *
 * Without this the page prerenders: at build the env var is unset, so
 * ``notFound()`` fires immediately, nothing touches ``cookies()``, and
 * Next bakes a static 404 into the output. Setting the variable on
 * Render restarts the service but does not rebuild it, so the chart
 * would stay 404 until the next deploy — on the one URL in the app
 * that is printed in a book.
 */
export const dynamic = 'force-dynamic'

export const metadata: Metadata = {
  title: 'Leadership Body Chart · Fresh Collective',
  description:
    'Generate your Human Design chart and see the shape of your natural leadership.',
}

export default function LeadershipBodyChartPage() {
  const chart = resolveChartEmbed()
  if (!chart.configured) notFound()

  return (
    <SiteShell>
      <section className="py-16 md:py-20">
        <Container>
          <div className="mx-auto max-w-[760px]">
            <h1 className="mb-5 font-serif text-4xl leading-tight text-navy-900 md:text-5xl">
              Your Human Design Bodychart
            </h1>
            <p className="mb-10 text-lg leading-relaxed text-[#4A5568]">
              Enter your birth details below to generate your Human Design
              chart — the map of how you are built to lead, decide and
              recover.
            </p>
          </div>
          <div className="mx-auto max-w-[980px]">
            <EmbedRenderer
              url={chart.url}
              provider={chart.provider}
              title="Human Design chart"
            />
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}
