import { notFound } from 'next/navigation'
import Link from 'next/link'
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

  const metaLine = series.ends_at
    ? `${new Date(series.starts_at).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })} – ${new Date(series.ends_at).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })}`
    : `Starts ${new Date(series.starts_at).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })} · Ongoing`

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
        initialSeries={series}
        initialGatherings={gatherings}
        initialPaymentOptions={paymentOptions}
        pathways={pathways}
      />
    </div>
  )
}
