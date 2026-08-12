import EventForm from '../EventForm'
import CreatorBackLink from '@/components/creator/CreatorBackLink'
import { getCreatorGatheringSeriesList, getCreatorPathways } from '@/lib/serverApi'
import type { CreatorGatheringSeriesSummary, CreatorPathway } from '@/types/platform'

export default async function NewEventPage({
  params, searchParams,
}: {
  params: Promise<{ slug: string }>
  searchParams: Promise<{ series_id?: string }>
}) {
  const { slug } = await params
  const { series_id: preselectedSeriesId } = await searchParams
  const [pathways, series]: [CreatorPathway[], CreatorGatheringSeriesSummary[]] = await Promise.all([
    getCreatorPathways(slug),
    getCreatorGatheringSeriesList(slug),
  ])
  // When arriving from a Series ("New Gathering in Series"), return
  // to that Series editor instead of the general Gatherings list.
  const contextSeries = preselectedSeriesId
    ? series.find((s) => s.id === preselectedSeriesId)
    : null
  const backHref = contextSeries
    ? `/creator-studio/gathering-series/${contextSeries.slug}`
    : '/creator-studio/gatherings'
  const backLabel = contextSeries
    ? `Back to ${contextSeries.title}`
    : 'Back to Gatherings'

  return (
    <div className="max-w-xl">
      <CreatorBackLink href={backHref} label={backLabel} />
      <div className="mb-8">
        <div className="mb-2 h-px w-6 bg-gold-400" />
        <h1 className="font-serif text-2xl text-navy-900">Create Gathering</h1>
      </div>
      <EventForm
        spaceSlug={slug}
        pathways={pathways}
        series={series}
        initialSeriesId={preselectedSeriesId ?? null}
      />
    </div>
  )
}
