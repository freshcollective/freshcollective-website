import Link from 'next/link'
import { getActiveCreatorSpace, getCreatorEvents, getCreatorGatheringSeriesList, getCreatorSpace } from '@/lib/serverApi'
import type { CreatorEvent, CreatorGatheringSeriesSummary, CreatorSpaceDetail } from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import PrimaryActionLink from '@/components/creator/PrimaryActionLink'
import GatheringSeriesBand from './GatheringSeriesBand'
import StandaloneGatheringCard from './StandaloneGatheringCard'

/**
 * Creator Studio → Gatherings.
 *
 * Shows only current + upcoming active Gatherings. Everything past
 * and everything cancelled lives in the archive. This page never
 * groups client-side — the scoped API is the single source of truth.
 */

export default async function GatheringsPage() {
  const primarySpace = await getActiveCreatorSpace()

  // Two scoped fetches: `upcoming` drives the list, `archive` is
  // only used to decide whether to expose the archive link.
  const [upcoming, past, spaceDetail, seriesList]: [
    CreatorEvent[],
    CreatorEvent[],
    CreatorSpaceDetail | null,
    CreatorGatheringSeriesSummary[],
  ] = primarySpace
    ? await Promise.all([
        getCreatorEvents(primarySpace.slug, 'upcoming'),
        getCreatorEvents(primarySpace.slug, 'archive'),
        getCreatorSpace(primarySpace.slug) as Promise<CreatorSpaceDetail | null>,
        getCreatorGatheringSeriesList(primarySpace.slug),
      ])
    : [[], [], null, []]

  const hasArchive = past.length > 0
  const now = Date.now()
  const hasFutureCancelled = past.some((e) => {
    if (e.status !== 'cancelled') return false
    const endMs = e.ends_at
      ? Date.parse(e.ends_at)
      : Date.parse(e.starts_at) + 60 * 60 * 1000
    return endMs > now
  })
  const archiveLinkLabel = hasFutureCancelled ? 'Gathering archive' : 'Past Gatherings'

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {primarySpace ? (
        <CollectiveArtworkHeader
          collectiveName={primarySpace.name}
          sectionTitle="Gatherings"
          meta="Live sessions, circles, workshops and community touchpoints."
          location={spaceDetail?.location ?? null}
          coverImageUrl={spaceDetail?.cover_image_url ?? null}
          action={
            <div className="flex items-center gap-4">
              {hasArchive && (
                <Link
                  href="/creator-studio/gatherings/archive"
                  className="text-[13px] font-medium text-white/85 underline-offset-4 transition-colors hover:text-white hover:underline"
                >
                  {archiveLinkLabel}
                </Link>
              )}
              <PrimaryActionLink href={`/creator/spaces/${primarySpace.slug}/events/new`}>
                Create Gathering
              </PrimaryActionLink>
            </div>
          }
        />
      ) : (
        <div className="mb-8">
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Gatherings</h1>
        </div>
      )}

      {/* No collective yet */}
      {!primarySpace && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Set up your collective first, then create Gatherings within it.
          </p>
          <Link
            href="/creator-studio/create"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create collective
          </Link>
        </div>
      )}

      {primarySpace && (
        <GatheringSeriesBand spaceSlug={primarySpace.slug} series={seriesList} />
      )}

      {/*
        Standalone Gatherings only. Anything with a semantic
        series_id belongs inside its Series editor; showing it here
        as well was duplication (the EMBODY Term 3 Series had all
        24 of its sessions repeated below the Series card). Backend
        rows are untouched — this is purely a Creator Studio
        presentation filter.
      */}
      {(() => {
        const standalone = primarySpace ? upcoming.filter((e) => !e.series_id) : []
        return (
          <>
            {primarySpace && (
              <div className="mb-3 mt-2 flex items-baseline justify-between">
                <h2 className="font-serif text-[16px] text-navy-900">
                  Standalone Gatherings
                </h2>
                <span className="text-[12px] text-slate-500">
                  Not part of a Gathering Series
                </span>
              </div>
            )}
            {primarySpace && standalone.length === 0 && (
              <div className="rounded-2xl border border-border bg-surface px-8 py-10 text-center">
                <p className="mb-1 font-serif text-lg text-navy-800">
                  No standalone Gatherings.
                </p>
                <p className="mx-auto max-w-md text-[13.5px] leading-relaxed text-black">
                  Any Gatherings you&rsquo;ve added to a Series live inside
                  their Series editor above. Create a standalone
                  Gathering &mdash; or add it to a Series &mdash; to see it here.
                </p>
              </div>
            )}
            {primarySpace && standalone.length > 0 && (
              <div className="grid gap-4 sm:grid-cols-2">
                {standalone.map((event) => (
                  <StandaloneGatheringCard key={event.id} event={event} slug={primarySpace.slug} />
                ))}
              </div>
            )}
          </>
        )
      })()}

      {/* Archive link — only when the archive has content */}
      {primarySpace && hasArchive && (
        <div className="mt-8 flex justify-center">
          <Link
            href="/creator-studio/gatherings/archive"
            className="rounded-full px-4 py-2 text-[13px] font-medium transition-colors"
            style={{
              background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
              color: 'var(--fc-accent, #0f766e)',
            }}
          >
            View Gathering archive →
          </Link>
        </div>
      )}

    </div>
  )
}
