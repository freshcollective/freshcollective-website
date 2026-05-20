// TODO (naming): Routes and backend models still use "events" internally. User-facing language is "Gatherings".
// TODO (booking system): add RSVP / reserve-a-spot action to each event card
// TODO (booking system): support capacity limits per event (creator-managed)
// TODO (booking system): booking status — available, full, booked, cancelled
// TODO (booking system): free events flow (RSVP with no payment)
// TODO (booking system): paid events — route to checkout, integrate Stripe
// TODO (booking system): attendee list visible to creator in Creator Studio
// TODO (booking system): booking confirmation email / reminder notifications
// TODO (booking system): creator toggle per-event: open / invite-only / closed

import { getSpaceEvents } from '@/lib/serverApi'
import GatheringsView from '@/components/spaces/GatheringsView'
import type { EventSummary } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpaceEventsPage({ params }: Props) {
  const { slug } = await params
  const events: EventSummary[] = await getSpaceEvents(slug)

  return (
    <div className="max-w-4xl">

      {/* ── Intro card — navy/gradient, matching Collective page ── */}
      <div
        className="mb-8 overflow-hidden rounded-2xl px-7 py-7"
        style={{
          background: '#071824',
          border: '1px solid rgba(66,199,198,0.10)',
          boxShadow: '0 4px 24px rgba(7,24,36,0.18), 0 1px 4px rgba(0,0,0,0.10)',
        }}
      >
        <div
          className="mb-3 h-[2px] w-8 rounded-full"
          style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
        />
        <h2 className="mb-2 leading-snug">
          <span
            className="inline-block text-2xl font-semibold"
            style={{
              background: 'linear-gradient(90deg, #55D7D2 0%, #D9FFFD 50%, #FFFFFF 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
          >
            Live Gatherings
          </span>
        </h2>
        <p className="text-[14px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.72)' }}>
          Live calls, workshops, and integration sessions. These are moments to gather,
          reflect, and move through the work together.
        </p>
      </div>

      {/* ── List / Calendar toggle + content ── */}
      <GatheringsView events={events} spaceSlug={slug} />

    </div>
  )
}
