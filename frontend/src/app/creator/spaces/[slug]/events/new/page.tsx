import EventForm from '../EventForm'

export default async function NewEventPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  return (
    <div className="max-w-xl">
      <div className="mb-8">
        <div className="mb-2 h-px w-6 bg-gold-400" />
        <h1 className="font-serif text-2xl text-navy-900">New event</h1>
      </div>
      <EventForm spaceSlug={slug} />
    </div>
  )
}
