import { notFound } from 'next/navigation'
import Link from 'next/link'
import { formatCalendarDate } from '@/lib/dateTime'
import {
  getActiveCreatorSpace,
  getCreatorGatheringSeries,
  getCreatorPathways,
  getCreatorSeriesGatherings,
  getCreatorSeriesPaymentOptions,
  getCreatorSpace,
} from '@/lib/serverApi'
import type {
  CreatorEvent,
  CreatorGatheringSeries,
  CreatorPathway,
  CreatorSeriesPaymentOption,
  CreatorSpaceDetail,
} from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import SeriesEditorClient from './SeriesEditorClient'

import { captureDegradedSurface } from '@/lib/sentryHandled'
/**
 * Gathering Series editor.
 *
 * Server component. Fetches the series + its attached Gatherings + its
 * Payment Options + the Creator's pathways (for the "Also include
 * Pathway access" picker) in one round trip and hands the tree to the
 * client editor. Detail lives in ``SeriesEditorClient``.
 */

interface Props {
  params: Promise<{ seriesSlug: string }>
}

async function _safe<T>(p: Promise<T>, label: string, fallback: T): Promise<T> {
  try {
    return await p
  } catch (err) {
    captureDegradedSurface(err, 'creator-gathering-series', label)
    console.error(`[creator-studio/gathering-series] ${label} failed:`, err)
    return fallback
  }
}

export default async function GatheringSeriesEditorPage({ params }: Props) {
  const { seriesSlug } = await params
  const activeSpace = await getActiveCreatorSpace()

  if (!activeSpace) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <div className="mb-8">
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Gathering Series</h1>
        </div>
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="text-[14px] leading-relaxed text-black">
            Select a Collective first from{' '}
            <Link href="/creator-studio" className="font-medium text-teal-700 hover:underline">
              My World
            </Link>{' '}
            to edit this Series.
          </p>
        </div>
      </div>
    )
  }

  const [series, gatherings, paymentOptions, pathways, spaceDetail]: [
    CreatorGatheringSeries | null,
    CreatorEvent[],
    CreatorSeriesPaymentOption[],
    CreatorPathway[],
    CreatorSpaceDetail | null,
  ] = await Promise.all([
    _safe(
      getCreatorGatheringSeries(activeSpace.slug, seriesSlug) as Promise<CreatorGatheringSeries | null>,
      'getCreatorGatheringSeries', null,
    ),
    _safe(getCreatorSeriesGatherings(activeSpace.slug, seriesSlug), 'getCreatorSeriesGatherings', []),
    _safe(getCreatorSeriesPaymentOptions(activeSpace.slug, seriesSlug), 'getCreatorSeriesPaymentOptions', []),
    _safe(getCreatorPathways(activeSpace.slug), 'getCreatorPathways', []),
    _safe(
      getCreatorSpace(activeSpace.slug) as Promise<CreatorSpaceDetail | null>,
      'getCreatorSpace', null,
    ),
  ])

  if (!series) notFound()

  // ``series.starts_at`` / ``series.ends_at`` are CALENDAR DATES
  // (set from ``<input type="date">``, stored as
  // ``YYYY-MM-DDT00:00:00`` and ``YYYY-MM-DDT23:59:59``). Use
  // ``formatCalendarDate`` which reads the date part directly and
  // formats without any UTC/timezone round-trip — otherwise the
  // ``23:59:59`` end-of-day encoding rolls into the next day in
  // Australia (23:59:59 UTC + 11h = 10:59 next-day AEDT).
  const spaceTimezone = spaceDetail?.timezone ?? 'Australia/Melbourne'
  const metaLine = series.ends_at
    ? `${formatCalendarDate(series.starts_at)} – ${formatCalendarDate(series.ends_at)}`
    : `Starts ${formatCalendarDate(series.starts_at)} · Ongoing`

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
      <CollectiveArtworkHeader
        collectiveName={activeSpace.name}
        sectionTitle={series.title}
        meta={metaLine}
        location={spaceDetail?.location ?? null}
        coverImageUrl={spaceDetail?.cover_image_url ?? null}
        backLink={{ href: '/creator-studio/gatherings', label: '← Back to Gatherings' }}
      />

      <SeriesEditorClient
        spaceSlug={activeSpace.slug}
        spaceTimezone={spaceTimezone}
        initialSeries={series}
        initialGatherings={gatherings}
        initialPaymentOptions={paymentOptions}
        pathways={pathways}
      />
    </div>
  )
}
