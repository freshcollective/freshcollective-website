import { notFound } from 'next/navigation'
import { getCreatorEvent, getCreatorEventBookings, getCreatorMembers, getCreatorPathways } from '@/lib/serverApi'
import type { CreatorPathway } from '@/types/platform'
import EventForm from '../EventForm'
import EventManagePanel from './EventManagePanel'

export default async function EditEventPage({
  params,
}: {
  params: Promise<{ slug: string; eventId: string }>
}) {
  const { slug, eventId } = await params
  const [event, bookings, members, pathways]: [
    Awaited<ReturnType<typeof getCreatorEvent>>,
    Awaited<ReturnType<typeof getCreatorEventBookings>>,
    Awaited<ReturnType<typeof getCreatorMembers>>,
    CreatorPathway[],
  ] = await Promise.all([
    getCreatorEvent(slug, eventId),
    getCreatorEventBookings(slug, eventId),
    getCreatorMembers(slug),
    getCreatorPathways(slug) as Promise<CreatorPathway[]>,
  ])
  if (!event) notFound()

  return (
    <div className="max-w-xl">
      <div className="mb-8">
        <div className="mb-2 h-px w-6 bg-gold-400" />
        {/* Internal route stays /events; visible term is Gathering. */}
        <h1 className="font-serif text-2xl text-navy-900">Edit Gathering</h1>
      </div>
      <EventForm spaceSlug={slug} event={event} pathways={pathways} />
      <EventManagePanel
        event={event}
        spaceSlug={slug}
        initialBookings={bookings}
        members={members}
      />
    </div>
  )
}
