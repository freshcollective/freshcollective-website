import { notFound } from 'next/navigation'
import {
  getCreatorBilling,
  getCreatorEvent,
  getCreatorEventBookings,
  getCreatorGatheringSeriesList,
  getCreatorMembers,
  getCreatorOfferPages,
  getCreatorPathways,
} from '@/lib/serverApi'
import type {
  CreatorGatheringSeriesSummary,
  CreatorOfferPageSummary,
  CreatorPathway,
} from '@/types/platform'
import CreatorBackLink from '@/components/creator/CreatorBackLink'
import OfferPagesShortcut from '@/app/creator-studio/offers/OfferPagesShortcut'
import SeriesChildOfferHint from '@/app/creator-studio/offers/SeriesChildOfferHint'
import EventForm from '../EventForm'
import EventManagePanel from './EventManagePanel'

async function _safe<T>(p: Promise<T>, label: string, fallback: T): Promise<T> {
  try {
    return await p
  } catch (err) {
    console.error(`[creator/events/edit] ${label} failed:`, err)
    return fallback
  }
}

export default async function EditEventPage({
  params, searchParams,
}: {
  params: Promise<{ slug: string; eventId: string }>
  searchParams: Promise<{ from_series?: string }>
}) {
  const { slug, eventId } = await params
  const { from_series: fromSeries } = await searchParams
  const [event, bookings, members, pathways, series, offers, billing]: [
    Awaited<ReturnType<typeof getCreatorEvent>>,
    Awaited<ReturnType<typeof getCreatorEventBookings>>,
    Awaited<ReturnType<typeof getCreatorMembers>>,
    CreatorPathway[],
    CreatorGatheringSeriesSummary[],
    CreatorOfferPageSummary[],
    Awaited<ReturnType<typeof getCreatorBilling>>,
  ] = await Promise.all([
    getCreatorEvent(slug, eventId),
    getCreatorEventBookings(slug, eventId),
    getCreatorMembers(slug),
    getCreatorPathways(slug) as Promise<CreatorPathway[]>,
    getCreatorGatheringSeriesList(slug),
    // Best-effort: the shortcut degrades to a "not on your plan"
    // state on failure rather than 500ing the Gathering editor.
    _safe(getCreatorOfferPages(slug), 'getCreatorOfferPages', []),
    _safe(getCreatorBilling(), 'getCreatorBilling', null),
  ])
  if (!event) notFound()

  const paidOffersEnabled = !!(
    billing?.is_platform_owner
    || billing?.current_plan?.paid_offers_enabled
  )

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

      {/* Offer Page shortcut for this Gathering.
          Standalone Gathering  → normal 0 / 1 / many Create/Edit card.
          Gathering in a Series → contextual card pointing to the
          Series Offer Page (or to creating one), so a Creator with
          a term like EMBODY doesn't end up making a separate Offer
          Page for every session. Backend still supports
          ``target_kind='gathering'`` for genuine one-offs. */}
      <div className="mt-6">
        {(() => {
          const parentSeries = event.series_id
            ? series.find((s) => s.id === event.series_id) ?? null
            : null
          if (parentSeries) {
            return (
              <SeriesChildOfferHint
                seriesId={parentSeries.id}
                seriesTitle={parentSeries.title}
                seriesSlug={parentSeries.slug}
                offers={offers}
                paidOffersEnabled={paidOffersEnabled}
              />
            )
          }
          return (
            <OfferPagesShortcut
              targetKind="gathering"
              targetId={event.id}
              targetTitle={event.title}
              offers={offers}
              paidOffersEnabled={paidOffersEnabled}
              variant="compact"
            />
          )
        })()}
      </div>

      <EventManagePanel
        event={event}
        spaceSlug={slug}
        initialBookings={bookings}
        members={members}
      />
    </div>
  )
}
