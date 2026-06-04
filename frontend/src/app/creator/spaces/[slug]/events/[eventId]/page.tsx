import { notFound } from 'next/navigation'
import { getCreatorEvent, getCreatorEventBookings, getCreatorMembers } from '@/lib/serverApi'
import EventForm from '../EventForm'
import EventManagePanel from './EventManagePanel'

export default async function EditEventPage({
  params,
}: {
  params: Promise<{ slug: string; eventId: string }>
}) {
  const { slug, eventId } = await params
  const [event, bookings, members] = await Promise.all([
    getCreatorEvent(slug, eventId),
    getCreatorEventBookings(slug, eventId),
    getCreatorMembers(slug),
  ])
  if (!event) notFound()

  return (
    <div className="max-w-xl">
      <div className="mb-8">
        <div className="mb-2 h-px w-6 bg-gold-400" />
        {/* TODO: Consider renaming internal /events routes to /gatherings later */}
        <h1 className="font-serif text-2xl text-navy-900">Edit gathering</h1>
      </div>
      <EventForm spaceSlug={slug} event={event} />
      <EventManagePanel
        event={event}
        spaceSlug={slug}
        initialBookings={bookings}
        members={members}
      />
    </div>
  )
}
