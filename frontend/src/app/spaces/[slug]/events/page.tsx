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
      <div
        className="mb-8 overflow-hidden rounded-2xl px-7 py-8"
        style={{
          background:
            'radial-gradient(rgba(66,199,198,0.07) 1px, transparent 1px), ' +
            'radial-gradient(ellipse at 80% 20%, rgba(66,199,198,0.22), transparent 45%), ' +
            'linear-gradient(135deg, #071824 0%, #073B3A 55%, #0F5E5C 100%)',
          backgroundSize: '22px 22px, auto, auto',
        }}
      >
        <div
          className="mb-3 h-[2px] w-8 rounded-full"
          style={{ background: 'linear-gradient(90deg, #42C7C6, transparent)' }}
        />
        <h2 className="font-serif text-2xl" style={{ color: '#FFFFFF' }}>Live Experiences</h2>
        <p className="mt-2 text-[14px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.65)' }}>
          Live calls, workshops, and integration sessions. These are moments to gather,
          reflect, and move through the work together.
        </p>
      </div>

      {events.length > 0 ? (
        <div className="flex flex-col gap-3">
          {events.map((e) => (
            <EventCard key={e.id} event={e} spaceSlug={slug} />
          ))}
        </div>
      ) : (
        <div className="rounded-2xl border border-teal-100 bg-white px-7 py-8">
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
