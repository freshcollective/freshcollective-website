import type { Metadata } from 'next'

import GuidesIndexClient from './GuidesIndexClient'
import Container from '@/components/layout/Container'
import SiteShell from '@/components/layout/SiteShell'
import { StarterKitBand } from '@/components/guides/StarterKit'
import { apiUrl } from '@/lib/api'
import type { GuideIndexPayload } from '@/lib/guides'
import { SERIF_HEADING } from '@/components/guides/serif'

/**
 * /guides — the index.
 *
 * Free, public articles for coaches, practitioners and teachers.
 * Readable signed out; nothing here is gated, and nothing here asks
 * for an account.
 *
 * The page ground is white rather than the warm canvas the other
 * marketing pages use. White was asked for, and the consequence is
 * that the cards carry their own hairline edge instead of borrowing
 * contrast from a tinted page — see ``GuideCard``.
 */

export const metadata: Metadata = {
  title: 'Guides · Fresh Collective',
  description:
    'Practical, honest guidance for coaches, practitioners and teachers '
    + 'building a home for their work, and for the people who gather '
    + 'around it.',
  alternates: { canonical: '/guides' },
  robots: { index: true, follow: true },
  openGraph: {
    title: 'Guides · Fresh Collective',
    description:
      'Practical, honest guidance for building a home for your work, and '
      + 'for the people who gather around it.',
    url: '/guides',
    type: 'website',
  },
}

/**
 * Never cached. Publishing shows up on the next request.
 *
 * This page was already dynamic before the fetch cache came off —
 * ``SiteShell`` reads ``cookies()`` to decide which header to show,
 * so every visit already reached the server and the only thing a
 * 300-second ``revalidate`` bought was a five-minute delay between
 * publishing a Guide and anyone being able to read it. Dropping it
 * costs one API call on a request that was happening anyway.
 *
 * The same property is what keeps a withdrawn Guide withdrawn:
 * unpublishing takes effect on the next request, unconditionally,
 * rather than depending on a cache-invalidation call having
 * succeeded. ``force-dynamic`` states that rather than leaving it to
 * be inferred from ``no-store``, so a future static opt-in has to be
 * a deliberate edit here.
 */
export const dynamic = 'force-dynamic'

async function loadGuides(): Promise<GuideIndexPayload> {
  try {
    const res = await fetch(apiUrl('/api/public/guides'), {
      cache: 'no-store',
    })
    if (!res.ok) return { guides: [], starter_kit_url: null }
    const data: unknown = await res.json()
    if (!data || typeof data !== 'object') {
      return { guides: [], starter_kit_url: null }
    }
    const payload = data as Partial<GuideIndexPayload>
    return {
      guides: Array.isArray(payload.guides) ? payload.guides : [],
      starter_kit_url:
        typeof payload.starter_kit_url === 'string'
          ? payload.starter_kit_url
          : null,
    }
  } catch {
    // An empty page beats a 500. Nothing here is private, so the
    // failure mode is "no Guides listed for a few minutes", not a
    // broken marketing surface.
    return { guides: [], starter_kit_url: null }
  }
}

export default async function GuidesIndexPage() {
  const { guides, starter_kit_url } = await loadGuides()

  return (
    <SiteShell>
      <div className="bg-white">
        <Container className="py-14 md:py-20">
          <header className="mx-auto mb-12 max-w-[42rem] text-center md:mb-14">
            <div
              aria-hidden="true"
              className="mx-auto mb-7 h-px w-10 bg-teal-500"
            />
            <h1
              className="text-[44px] leading-[1.05] tracking-[-0.03em] text-navy-950 md:text-[56px]"
              style={SERIF_HEADING}
            >
              Guides
            </h1>
            <p className="mx-auto mt-6 max-w-[34rem] font-serif text-[18px] italic leading-[1.6] text-navy-700 md:text-[19px]">
              Practical, honest guidance for building a home for your work, and
              for the people who gather around it.
            </p>
          </header>

          <GuidesIndexClient guides={guides} />

          <div className="mt-16 md:mt-20">
            <StarterKitBand url={starter_kit_url} />
          </div>
        </Container>
      </div>
    </SiteShell>
  )
}
