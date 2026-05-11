import { getSpaceEvents } from '@/lib/serverApi'
import EventCard from '@/components/spaces/EventCard'
import type { EventSummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpaceEventsPage({ params }: Props) {
  const { slug } = await params
  const events: EventSummary[] = await getSpaceEvents(slug)

  return (
    <div className="max-w-2xl">
      <div className="mb-2 h-px w-6 bg-gold-500" />
      <h2 className="mb-2 font-serif text-2xl text-navy-900">Live Experiences</h2>
      <p className="mb-8 text-sm leading-relaxed text-slate-500">
        Live calls, workshops, and integration sessions. These are moments to gather,
        reflect, and move through the work together.
      </p>

      {events.length > 0 ? (
        <div className="flex flex-col gap-3">
          {events.map((e) => (
            <EventCard key={e.id} event={e} spaceSlug={slug} />
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-surface px-7 py-8">
          <p className="mb-1 font-serif text-lg text-navy-700">
            No upcoming sessions yet.
          </p>
          <p className="text-sm leading-relaxed text-slate-400">
            Live calls, workshops, and gatherings will appear here when scheduled.
            Check back soon.
          </p>
        </div>
      )}
    </div>
  )
}
