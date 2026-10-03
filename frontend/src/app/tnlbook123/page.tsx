/**
 * /tnlbook123 — preserved legacy URL (Natural Leader Book Companion).
 *
 * Book owners may have this path, so it keeps resolving after the
 * freshcollective.au cutover. The old Wix page is deliberately not
 * rebuilt; the URL is what matters.
 *
 * Deliberately minimal. The companion's actual downloads and resource
 * links are not in this repository and were not supplied, and inventing
 * them would be worse than omitting them — a book owner following a
 * printed URL to a list of dead links is a sharper failure than finding
 * a short, honest page. What is here is only what could be stated
 * truthfully: what the page is, and the chart URL, which is itself a
 * preserved route.
 *
 * Longer term the companion resources are expected to live inside a
 * future Lindsey-led Collective; this page is the launch placeholder for
 * the URL, not that destination.
 */

import type { Metadata } from 'next'
import Link from 'next/link'

import Container from '@/components/layout/Container'
import SiteShell from '@/components/layout/SiteShell'

export const metadata: Metadata = {
  title: 'Natural Leader Book Companion · Fresh Collective',
  description:
    'Companion resources for the Natural Leader book, including your Human Design chart.',
}

export default function NaturalLeaderBookCompanionPage() {
  return (
    <SiteShell>
      <section className="py-16 md:py-20">
        <Container>
          <div className="mx-auto max-w-[680px]">
            <h1 className="mb-5 font-serif text-4xl leading-tight text-navy-900 md:text-5xl">
              Natural Leader Book Companion
            </h1>
            <p className="mb-6 text-lg leading-relaxed text-[#4A5568]">
              Thank you for reading <em>The Natural Leader</em>. The companion
              material lives here.
            </p>
            <p className="mb-10 text-lg leading-relaxed text-[#4A5568]">
              Start with your Human Design chart — the map the book refers to
              throughout.
            </p>

            <Link
              href="/leadershipbodychart"
              className="inline-flex items-center gap-2 rounded-lg bg-teal-600 px-5 py-3 text-[15px] font-semibold text-white transition hover:bg-teal-700"
            >
              Generate your Leadership Body Chart
            </Link>

            <div className="mt-12 border-t border-border pt-8">
              <p className="text-[15px] leading-relaxed text-[#4A5568]">
                More companion resources are being gathered into Fresh
                Collective. In the meantime you can{' '}
                <Link href="/spaces" className="text-teal-700 underline">
                  explore the Collectives
                </Link>{' '}
                or{' '}
                <Link href="/discover-places" className="text-teal-700 underline">
                  discover the Places
                </Link>
                .
              </p>
            </div>
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}
