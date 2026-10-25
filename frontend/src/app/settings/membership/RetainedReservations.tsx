/**
 * Gatherings a former member still holds a paid place at.
 *
 * The "practical way to locate it" half of the paid-reservation
 * exception: leaving a Collective preserves a reservation that was
 * bought, and without this band finding it again would depend on the
 * person still having the Gathering's URL.
 *
 * Renders nothing when there is nothing — which is the case for
 * everybody who has not left a Collective holding a paid booking. It
 * sits on the Membership page because that is where leaving happened,
 * and immediately after the Collectives band so the relationship
 * between "this is no longer listed" and "but you still have this" is
 * readable in one glance.
 *
 * A server component: the list never changes in response to anything on
 * this page except a departure, which already refreshes it.
 */

import Link from 'next/link'
import type { RetainedReservation } from '@/types/platform'

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString('en-AU', {
    weekday: 'short', day: 'numeric', month: 'short',
    hour: 'numeric', minute: '2-digit',
  })
}

export default function RetainedReservations({
  reservations,
}: {
  reservations: RetainedReservation[]
}) {
  if (reservations.length === 0) return null

  return (
    <section className="mb-8">
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-black">
        Reservations you still hold
      </p>
      <div className="flex flex-col gap-3">
        {reservations.map((r) => (
          <div
            key={r.booking_id}
            className="flex items-center justify-between overflow-hidden rounded-2xl border border-border bg-white px-6 py-4 transition-shadow hover:shadow-sm"
            style={{ boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
          >
            <div>
              <Link
                href={`/spaces/${r.space_slug}/events/${r.event_id}`}
                className="text-[14px] font-medium text-navy-800 transition-colors hover:text-teal-700"
              >
                {r.event_title}
              </Link>
              <p className="mt-0.5 text-[12px] text-black">
                {formatWhen(r.starts_at)} · {r.space_name}
              </p>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-2.5 text-[12px] leading-relaxed text-black">
        You paid for these, so they are still yours even though you have
        left the Collective. Open one to see joining details or to cancel.
      </p>
    </section>
  )
}
