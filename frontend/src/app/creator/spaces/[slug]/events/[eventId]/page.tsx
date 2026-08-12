import { notFound } from 'next/navigation'
import { getCreatorEvent, getCreatorEventBookings, getCreatorGatheringSeriesList, getCreatorMembers, getCreatorPathways } from '@/lib/serverApi'
import type { CreatorGatheringSeriesSummary, CreatorPathway } from '@/types/platform'
import CreatorBackLink from '@/components/creator/CreatorBackLink'
import EventForm from '../EventForm'
import EventManagePanel from './EventManagePanel'

export default async function EditEventPage({
  params, searchParams,
}: {
  params: Promise<{ slug: string; eventId: string }>
  searchParams: Promise<{ from_series?: string }>
}) {
  const { slug, eventId } = await params
  const { from_series: fromSeries } = await searchParams
  const [event, bookings, members, pathways, series]: [
    Awaited<ReturnType<typeof getCreatorEvent>>,
    Awaited<ReturnType<typeof getCreatorEventBookings>>,
    Awaited<ReturnType<typeof getCreatorMembers>>,
    CreatorPathway[],
    CreatorGatheringSeriesSummary[],
  ] = await Promise.all([
    getCreatorEvent(slug, eventId),
    getCreatorEventBookings(slug, eventId),
    getCreatorMembers(slug),
    getCreatorPathways(slug) as Promise<CreatorPathway[]>,
    getCreatorGatheringSeriesList(slug),
  ])
  if (!event) notFound()

  // Contextual back-link. When the Creator arrived from a specific
  // Gathering Series editor (via ``?from_series=<slug>``), return them
  // to that Series; otherwise back to the general Gatherings list.
  const contextSeries = fromSeries ? series.find((s) => s.slug === fromSeries) : null
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
        {/* Internal route stays /events; visible term is Gathering. */}
        <h1 className="font-serif text-2xl text-navy-900">Edit Gathering</h1>
      </div>
      <EventForm spaceSlug={slug} event={event} pathways={pathways} series={series} />
      <EventManagePanel
        event={event}
        spaceSlug={slug}
        initialBookings={bookings}
        members={members}
      />
    </div>
  )
}
