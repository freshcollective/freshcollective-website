import Link from 'next/link'
import type { EventSummary } from '@/types/platform'
import { formatGatheringDate } from '@/lib/dateTime'
import { getGatheringAccent } from '@/lib/gatheringAccent'

const LOCATION_LABEL: Record<string, string> = {
  zoom: 'Live — Zoom',
  in_person: 'In Person',
  async_recorded: 'Recorded',
}

interface EventCardProps {
  event: EventSummary
  spaceSlug: string
  timezone: string
  isMember?: boolean
  onBook?: () => void
  onCancelBooking?: () => void
  onBookSeries?: () => void
}

export default function EventCard({
  event,
  spaceSlug,
  timezone,
  isMember = true,
  onBook,
  onCancelBooking,
  onBookSeries,
}: EventCardProps) {
  const { day, month, time } = formatGatheringDate(event.starts_at, timezone)
  const locationLabel = LOCATION_LABEL[event.location_type] ?? event.location_type
  const href = `/spaces/${spaceSlug}/events/${event.id}`
  const accent = getGatheringAccent(event.location_type)

  const isCancelled = event.status === 'cancelled'
  const isBooked = event.my_booking_status === 'confirmed'
  const isFull = event.spots_remaining !== null && event.spots_remaining === 0 && !isBooked
  const bookingClosed = !event.can_book && !isBooked && event.requires_booking && !isFull && !isMember

  const spotsLabel =
    event.requires_booking && event.spots_remaining !== null
      ? event.spots_remaining === 0
        ? 'Full'
        : `${event.spots_remaining} spot${event.spots_remaining === 1 ? '' : 's'} left`
      : null

  const seriesLabel = event.recurrence_index && event.recurrence_total
    ? `Session ${event.recurrence_index} of ${event.recurrence_total}`
    : event.recurrence_label
    ? event.recurrence_label
    : null

  return (
    <div
      className="group flex flex-col rounded-2xl border bg-white transition-all hover:-translate-y-0.5 hover:shadow-md"
      style={{
        borderColor: isCancelled ? 'rgba(0,0,0,0.10)' : `${accent.border}33`,
        borderLeft: `3px solid ${isCancelled ? '#cbd5e1' : accent.border}`,
        opacity: isCancelled ? 0.7 : 1,
      }}
    >
      {/* Thumbnail image (optional) */}
      {event.thumbnail_url && (
        <div className="relative h-36 w-full overflow-hidden rounded-t-2xl">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={event.thumbnail_url}
            alt={event.title}
            className="h-full w-full object-cover"
          />
          {isCancelled && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/40">
              <span className="rounded-full bg-white/90 px-3 py-1 text-xs font-semibold text-slate-700">
                Cancelled
              </span>
            </div>
          )}
        </div>
      )}

      {/* Main content — navigates to event detail */}
      <Link href={href} className="flex items-start gap-5 p-5">
        {/* Date block */}
        <div className="shrink-0 text-center">
          <div className="text-2xl font-bold leading-none text-navy-900">{day}</div>
          <div className="mt-0.5 text-xs font-semibold uppercase tracking-wider" style={{ color: accent.monthColor }}>{month}</div>
        </div>

        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            {isCancelled ? (
              <span className="rounded-full px-2.5 py-0.5 text-xs font-semibold"
                style={{ background: 'rgba(0,0,0,0.06)', color: '#94a3b8' }}>
                Cancelled
              </span>
            ) : (
              <span
                className="rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{ background: accent.pillBg, color: accent.pillColor }}
              >
                {locationLabel}
              </span>
            )}
            <span className="text-xs text-slate-400">{time}</span>
            {seriesLabel && (
              <span className="rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{ background: 'rgba(56,160,158,0.07)', color: '#38A09E' }}>
                {seriesLabel}
              </span>
            )}
            {spotsLabel && (
              <span
                className="rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{
                  background: isFull ? 'rgba(0,0,0,0.06)' : 'rgba(214,177,63,0.12)',
                  color: isFull ? '#94a3b8' : '#7A5A00',
                }}
              >
                {spotsLabel}
              </span>
            )}
            {event.is_public && !isMember && (
              <span className="rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{ background: 'rgba(214,177,63,0.10)', color: '#7A5A00' }}>
                Members only to book
              </span>
            )}
          </div>
          <p className="font-medium text-navy-900 transition-colors group-hover:text-teal-700">
            {event.title}
          </p>
          {event.description && (
            <p className="mt-1 line-clamp-2 text-sm leading-relaxed text-slate-500">
              {event.description.split('\n')[0]}
            </p>
          )}
        </div>

        <span className="shrink-0 self-center text-slate-300 transition-colors group-hover:text-teal-400">
          →
        </span>
      </Link>

      {/* Booking row — only shown if booking is relevant and event is not cancelled */}
      {event.requires_booking && !isCancelled && (
        <div className="flex flex-wrap items-center gap-3 border-t px-5 py-3" style={{ borderColor: `${accent.border}22` }}>
          {isBooked ? (
            <>
              <span
                className="rounded-full px-2.5 py-0.5 text-xs font-semibold"
                style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}
              >
                Booked ✓
              </span>
              {event.can_cancel_booking && onCancelBooking && (
                <button
                  onClick={onCancelBooking}
                  className="text-xs text-slate-400 underline hover:text-slate-600"
                >
                  Cancel booking
                </button>
              )}
            </>
          ) : !isMember ? (
            <Link
              href={`/spaces/${spaceSlug}/about`}
              className="text-xs font-medium text-teal-600 hover:underline"
            >
              Join to book →
            </Link>
          ) : isFull ? (
            <span className="text-xs text-slate-400">Session full</span>
          ) : bookingClosed ? (
            <span className="text-xs text-slate-400">Booking closed</span>
          ) : event.can_book && onBook ? (
            <button
              onClick={onBook}
              className="rounded-lg px-4 py-1.5 text-xs font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              Book your spot
            </button>
          ) : event.booking_note ? (
            <span className="text-xs text-slate-400">{event.booking_note}</span>
          ) : null}

          {/* Series booking — only show if not already booked into all sessions */}
          {event.recurrence_series_id && event.can_book && onBookSeries && (
            <button
              onClick={onBookSeries}
              className="rounded-lg border border-teal-200 px-3 py-1.5 text-xs font-medium text-teal-700 transition-colors hover:bg-teal-50"
            >
              Book all sessions
            </button>
          )}
        </div>
      )}
    </div>
  )
}
