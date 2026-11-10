import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'

import Container from '@/components/layout/Container'
import GuideBody from '@/components/guides/GuideBody'
import GuideClosingBand from '@/components/guides/GuideClosingBand'
import GuideCta from '@/components/guides/GuideCta'
import OnThisPage from '@/components/guides/OnThisPage'
import { StarterKitCard } from '@/components/guides/StarterKit'
import { serverFetch } from '@/lib/serverApi'
import { SERIF_HEADING } from '@/components/guides/serif'
import {
  authorInitial,
  bylineFor,
  categoryLabel,
  extractHeadings,
  formatGuideDate,
  readingTimeLabel,
  type GuideArticle,
} from '@/lib/guides'

/**
 * A draft, as a reader would see it.
 *
 * The same components the public article page uses — ``GuideBody``,
 * ``OnThisPage``, ``GuideCta``, ``GuideClosingBand`` — so this shows
 * the real thing rather than an approximation that drifts. What it
 * deliberately does not share is the chrome: no ``SiteShell``, because
 * this is reached from inside the admin and swapping to the public
 * header mid-session is disorienting, and a preview banner across the
 * top so nobody mistakes this for the live page.
 *
 * Admin-only by the admin layout and by the API behind it, and
 * ``noindex`` regardless — a preview URL that leaked into an index
 * would publish a draft by the back door.
 */

export const metadata: Metadata = {
  title: 'Guide preview · Fresh Collective',
  robots: { index: false, follow: false },
}

export const dynamic = 'force-dynamic'

export default async function GuidePreviewPage(
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params
  const res = await serverFetch(`/api/admin/guides/${id}`)
  if (!res.ok) notFound()
  const guide = (await res.json()) as GuideArticle & { status: string }

  const settings = await serverFetch('/api/admin/guides/settings')
  const starterKitUrl = settings.ok
    ? ((await settings.json())?.starter_kit_url ?? null)
    : null

  const headings = extractHeadings(guide.body)

  return (
    <div className="-mx-6 -my-6 bg-white md:-mx-10">
      <div className="bg-navy-950 px-6 py-3 text-[13px] text-white md:px-10">
        <Container>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>
              Preview · this Guide is {guide.status === 'published'
                ? 'published'
                : 'a draft and not public'}
            </span>
            <Link
              href={`/admin/guides/${id}`}
              className="rounded-sm font-semibold text-teal-300 hover:text-teal-200"
            >
              ← Back to the editor
            </Link>
          </div>
        </Container>
      </div>

      <Container className="py-10 md:py-14">
        <nav aria-label="Breadcrumb" className="mb-7">
          <ol className="flex flex-wrap items-center gap-2 text-[14px]">
            <li className="text-teal-700">Guides</li>
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

        <div className="mt-12 grid gap-10 lg:mt-14 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-14">
          <div className="min-w-0 max-w-[44rem]">
            <GuideBody html={guide.body} />
            <GuideCta guide={guide} />
          </div>
          <aside className="min-w-0 space-y-6 lg:sticky lg:top-8 lg:self-start">
            <OnThisPage headings={headings} />
            <StarterKitCard url={starterKitUrl} />
          </aside>
        </div>

      </Container>

      {/* Outside the Container — see the note on the public page. */}
      <GuideClosingBand />
    </div>
  )
}
