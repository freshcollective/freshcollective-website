import type { Metadata } from 'next'

import GuidesIndexClient from './GuidesIndexClient'
import Container from '@/components/layout/Container'
import PageHero from '@/components/layout/PageHero'
import SiteShell from '@/components/layout/SiteShell'
import { StarterKitBand } from '@/components/guides/StarterKit'
import { apiUrl } from '@/lib/api'
import type { GuideIndexPayload } from '@/lib/guides'

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

/**
 * The line under the heading, and the base of the page's description.
 *
 * One constant for both so they cannot drift — the meta description
 * was previously a longer rewrite of the old subtitle and had to be
 * changed in two places.
 */
const GUIDES_SUBTITLE =
  'Ideas, stories and how-tos for anyone who brings people together.'

export const metadata: Metadata = {
  title: 'Guides · Fresh Collective',
  description: `${GUIDES_SUBTITLE} Free, practical writing from Fresh Collective.`,
  alternates: { canonical: '/guides' },
  robots: { index: true, follow: true },
  openGraph: {
    title: 'Guides · Fresh Collective',
    description: GUIDES_SUBTITLE,
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

const EMPTY: GuideIndexPayload = {
  guides: [],
  starter_kit_url: null,
  header_image_url: null,
  header_image_alt: null,
}

async function loadGuides(): Promise<GuideIndexPayload> {
  try {
    const res = await fetch(apiUrl('/api/public/guides'), {
      cache: 'no-store',
    })
    if (!res.ok) return EMPTY
    const data: unknown = await res.json()
    if (!data || typeof data !== 'object') {
      return EMPTY
    }
    const payload = data as Partial<GuideIndexPayload>
    return {
      guides: Array.isArray(payload.guides) ? payload.guides : [],
      starter_kit_url:
        typeof payload.starter_kit_url === 'string'
          ? payload.starter_kit_url
          : null,
      header_image_url:
        typeof payload.header_image_url === 'string'
          ? payload.header_image_url
          : null,
      header_image_alt:
        typeof payload.header_image_alt === 'string'
          ? payload.header_image_alt
          : null,
    }
  } catch {
    // An empty page beats a 500. Nothing here is private, so the
    // failure mode is "no Guides listed for a few minutes", not a
    // broken marketing surface.
    return EMPTY
  }
}

export default async function GuidesIndexPage() {
  const {
    guides, starter_kit_url, header_image_url, header_image_alt,
  } = await loadGuides()

  return (
    <SiteShell>
      <div className="bg-white">
        {/* The same contained navy card Explore Collectives and
            Discover Places use, including its ``h1`` — reused rather
            than restyled, so the three destinations stay one family.
            ``bandBackground`` is white because this page is white
            throughout, where the member destinations sit on the warm
            off-white. */}
        <PageHero
          title="Guides"
          supportingCopy={GUIDES_SUBTITLE}
          bandBackground="#FFFFFF"
          align="center"
          accentTone="gold"
          backgroundImage={
            header_image_url
              ? { url: header_image_url, alt: header_image_alt ?? '' }
              : null
          }
        />

        <Container className="pb-14 pt-10 md:pb-20 md:pt-12">
          <GuidesIndexClient guides={guides} />

          <div className="mt-16 md:mt-20">
            <StarterKitBand url={starter_kit_url} />
          </div>
        </Container>
      </div>
    </SiteShell>
  )
}
