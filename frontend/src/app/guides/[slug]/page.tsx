import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'

import Container from '@/components/layout/Container'
import SiteShell from '@/components/layout/SiteShell'
import GuideBody from '@/components/guides/GuideBody'
import GuideCard from '@/components/guides/GuideCard'
import GuideClosingBand from '@/components/guides/GuideClosingBand'
import GuideCta from '@/components/guides/GuideCta'
import OnThisPage from '@/components/guides/OnThisPage'
import { StarterKitCard } from '@/components/guides/StarterKit'
import { apiUrl } from '@/lib/api'
import { SITE_ORIGIN, DEFAULT_SOCIAL_IMAGE } from '@/lib/collectiveSeo'
import { SERIF_HEADING } from '@/components/guides/serif'
import {
  authorInitial,
  bylineFor,
  categoryLabel,
  extractHeadings,
  formatGuideDate,
  guideJsonLd,
  guidePath,
  guideSeoDescription,
  guideSeoTitle,
  readingTimeLabel,
  type GuideArticlePayload,
} from '@/lib/guides'

/**
 * /guides/[slug] — one Guide.
 *
 * A draft and a slug that never existed both arrive here as a 404
 * from the API and both leave as ``notFound()``. That is deliberate:
 * distinguishing them would tell an anonymous reader that an
 * unpublished Guide exists, which is the one thing draft status is
 * for.
 */

/**
 * Never cached — see the note on ``/guides``.
 *
 * It matters more here than there. A cached article is a Guide that
 * stays readable after it has been unpublished, for as long as the
 * cache window lasts; with no cache, the withdrawal is complete on
 * the next request and does not depend on anything else working.
 */
export const dynamic = 'force-dynamic'

async function loadGuide(slug: string): Promise<GuideArticlePayload | null> {
  try {
    const res = await fetch(
      apiUrl(`/api/public/guides/${encodeURIComponent(slug)}`),
      { cache: 'no-store' },
    )
    if (!res.ok) return null
    const data: unknown = await res.json()
    if (!data || typeof data !== 'object') return null
    const payload = data as Partial<GuideArticlePayload>
    if (!payload.guide || typeof payload.guide !== 'object') return null
    return {
      guide: payload.guide,
      related: Array.isArray(payload.related) ? payload.related : [],
      starter_kit_url:
        typeof payload.starter_kit_url === 'string'
          ? payload.starter_kit_url
          : null,
    }
  } catch {
    return null
  }
}

export async function generateMetadata(
  { params }: { params: Promise<{ slug: string }> },
): Promise<Metadata> {
  const { slug } = await params
  const payload = await loadGuide(slug)
  if (!payload) {
    // Nothing to describe, and nothing that should be indexed.
    return { title: 'Guide not found · Fresh Collective', robots: { index: false } }
  }
  const { guide } = payload
  const title = guideSeoTitle(guide)
  const description = guideSeoDescription(guide)
  const image = guide.hero_image_url ?? DEFAULT_SOCIAL_IMAGE

  return {
    title: `${title} · Fresh Collective`,
    description,
    alternates: { canonical: guidePath(guide.slug) },
    robots: { index: true, follow: true },
    openGraph: {
      title,
      description,
      url: guidePath(guide.slug),
      type: 'article',
      publishedTime: guide.published_at ?? undefined,
      modifiedTime: guide.updated_at,
      images: [{ url: image, alt: guide.hero_image_alt ?? title }],
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description,
      images: [image],
    },
  }
}

export default async function GuidePage(
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params
  const payload = await loadGuide(slug)
  if (!payload) notFound()

  const { guide, related, starter_kit_url } = payload
  const headings = extractHeadings(guide.body)

  return (
    <SiteShell>
      <div className="bg-white">
        <Container className="py-10 md:py-14">
          {/* Breadcrumb. The category is not a link: there is no
              per-category page, and a link that only filters the
              index would promise a destination it does not have. */}
          <nav aria-label="Breadcrumb" className="mb-7">
            <ol className="flex flex-wrap items-center gap-2 text-[14px]">
              <li>
                <Link
                  href="/guides"
                  className="rounded-sm text-teal-700 transition-colors hover:text-teal-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-2"
                >
                  Guides
                </Link>
              </li>
              <li aria-hidden="true" className="text-navy-300">/</li>
              <li className="text-navy-700">{categoryLabel(guide.category)}</li>
            </ol>
          </nav>

          <header className="max-w-[50rem]">
            <h1
            className="text-[34px] leading-[1.1] tracking-[-0.03em] text-navy-950 md:text-[48px] lg:text-[56px]"
            style={SERIF_HEADING}
          >
              {guide.title}
            </h1>
            {guide.standfirst && (
              <p className="mt-6 font-serif text-[19px] italic leading-[1.55] text-navy-700 md:text-[21px]">
                {guide.standfirst}
              </p>
            )}

            <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3 text-[14px] text-navy-700">
              <span className="flex items-center gap-3">
                <span
                  aria-hidden="true"
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-teal-50 font-serif text-[14px] text-teal-800"
                >
                  {authorInitial(guide.author_name)}
                </span>
                {bylineFor(guide.author_name)}
              </span>
              <span>{readingTimeLabel(guide.reading_time_minutes)}</span>
              <span>Updated {formatGuideDate(guide.updated_at)}</span>
            </div>
          </header>

          {guide.hero_image_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={guide.hero_image_url}
              alt={guide.hero_image_alt ?? ''}
              className="mt-10 aspect-[16/7] w-full rounded-2xl object-cover"
            />
          )}

          {/* Two columns from lg up. The side column stacks below the
              article on anything narrower, so a phone reads the Guide
              first and the contents list never pushes it down. */}
          <div className="mt-12 grid gap-10 lg:mt-14 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-14">
            <div className="min-w-0 max-w-[44rem]">
              <GuideBody html={guide.body} />
              <GuideCta guide={guide} />
            </div>

            <aside className="min-w-0 space-y-6 lg:sticky lg:top-8 lg:self-start">
              <OnThisPage headings={headings} />
              <StarterKitCard url={starter_kit_url} />
            </aside>
          </div>

        </Container>

        {/* Outside the article's Container on purpose:
            ``ClosingInvitation`` brings its own section and Container,
            and nesting them would double the page padding. */}
        <GuideClosingBand />

        {related.length > 0 && (
          <Container className="pb-16 md:pb-20">
            <section aria-labelledby="keep-reading">
              <h2
                id="keep-reading"
                className="mb-6 text-[24px] leading-[1.2] text-navy-950 md:mb-8 md:text-[26px]"
                style={SERIF_HEADING}
              >
                Keep reading
              </h2>
              <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
                {related.map((g) => (
                  <GuideCard key={g.slug} guide={g} compact />
                ))}
              </div>
            </section>
          </Container>
        )}
      </div>

      {/* Article structured data, serialised from the same values the
          page renders above. */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(guideJsonLd(guide, SITE_ORIGIN)),
        }}
      />
    </SiteShell>
  )
}
