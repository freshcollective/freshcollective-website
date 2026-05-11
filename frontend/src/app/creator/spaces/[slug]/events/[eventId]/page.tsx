import { notFound } from 'next/navigation'
import { getCreatorEvent } from '@/lib/serverApi'
import EventForm from '../EventForm'

export default async function EditEventPage({
  params,
}: {
  params: Promise<{ slug: string; eventId: string }>
}) {
  const { slug, eventId } = await params
  const event = await getCreatorEvent(slug, eventId)
  if (!event) notFound()

  return (
    <div className="max-w-xl">
      <div className="mb-8">
        <div className="mb-2 h-px w-6 bg-gold-400" />
        <h1 className="font-serif text-2xl text-navy-900">Edit event</h1>
      </div>
      <EventForm spaceSlug={slug} event={event} />
    </div>
  )
}
