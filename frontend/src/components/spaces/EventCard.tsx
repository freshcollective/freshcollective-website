import Link from 'next/link'
import type { EventSummary } from '@/types/platform'
import { countdownLabel, formatGatheringDate } from '@/lib/dateTime'
import { getGatheringAccent } from '@/lib/gatheringAccent'
import { formatMoneyCents } from '@/lib/formatMoney'
import {
  gatheringIcon, gatheringLabel,
  attendanceFormatLabel,
  accessTypeMeta,
} from '@/lib/gatheringTypes'

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
  /** Archive rendering — no countdown, no reservation actions,
   *  a calm "Past Gathering" pill, and a Watch replay / View
   *  Gathering CTA depending on what's available. Cards still
   *  navigate to the existing detail URL. */
  archive?: boolean
}

/**
 * EventCard — a Gathering card in the member list.
 *
 * Visual hierarchy (top → bottom):
 *   ▸ Cover image (if any) or type-icon block
 *   ▸ Header row  — type chip · format chip · access chip · countdown
 *   ▸ Date + title + one-line description
 *   ▸ Availability + primary action row
 *
 * The card is meant to feel inviting, not administrative — icons over
 * text where possible, calm colour, one-line intro so the eye reads
 * the whole card in a glance.
 */

export default function EventCard({
  event,
  spaceSlug,
  timezone,
  isMember = true,
  onBook,
  onCancelBooking,
  onBookSeries,
  archive = false,
}: EventCardProps) {
  const { day, month, time } = formatGatheringDate(event.starts_at, timezone)
  const locationLabel = event.attendance_format
    ? attendanceFormatLabel(event.attendance_format)
    : (LOCATION_LABEL[event.location_type] ?? event.location_type)
  const href = `/spaces/${spaceSlug}/events/${event.id}`
  const accent = getGatheringAccent(event.location_type)
  const access = accessTypeMeta(event.booking_access_type)
  const typeIcon = gatheringIcon(event.gathering_type)
  const typeLabel = gatheringLabel(event.gathering_type)
  const countdown = event.status === 'cancelled' || archive
    ? null
    : countdownLabel(event.starts_at, event.ends_at ?? null)
  const oneLine = event.description
    ? event.description.split('\n').find((line) => line.trim().length > 0)?.trim() ?? null
    : null

  const isCancelled = event.status === 'cancelled'
  const isReserved  = event.my_booking_status === 'confirmed'
  const isFull = event.spots_remaining !== null && event.spots_remaining === 0 && !isReserved
  const bookingClosed = !event.can_book && !isReserved && event.requires_booking && !isFull && !isMember

  // Countdown pill styling — "Live now" gets a soft pulse, otherwise
  // calm neutral. Ended / null / archive → no pill.
  const isLive = countdown === 'Live now'
  const showCountdown = !!countdown && countdown !== 'Ended'

  // Availability line is only meaningful for current Gatherings —
  // hide it in archive so past events don't advertise capacity.
  const placesLabel = archive
    ? null
    : event.requires_booking && event.spots_remaining !== null
      ? event.spots_remaining === 0
        ? 'All places taken'
        : `${event.spots_remaining} place${event.spots_remaining === 1 ? '' : 's'} remaining`
      : null

  const seriesLabel = event.recurrence_index && event.recurrence_total
    ? `Gathering ${event.recurrence_index} of ${event.recurrence_total}`
    : event.recurrence_label
    ? event.recurrence_label
    : null

  return (
    <div
      className="group flex flex-col overflow-hidden rounded-2xl border bg-white transition-all hover:-translate-y-0.5 hover:shadow-md"
      style={{
        borderColor: isCancelled ? 'rgba(0,0,0,0.10)' : `${accent.border}33`,
        borderLeft: `3px solid ${isCancelled ? '#cbd5e1' : accent.border}`,
        opacity: isCancelled ? 0.7 : 1,
      }}
    >
      {/* Cover image — only rendered when the caretaker has provided
          one. No placeholder icon block when the cover is absent;
          the card leans on its date block + title + chip row instead
          for a cleaner, calmer look across a long schedule. */}
      {event.thumbnail_url && (
        <div className="relative h-36 w-full overflow-hidden">
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

      <Link href={href} className="flex items-start gap-5 p-5">
        {/* Date block */}
        <div className="shrink-0 text-center">
          <div className="text-2xl font-bold leading-none text-navy-900">{day}</div>
          <div className="mt-0.5 text-xs font-semibold uppercase tracking-wider" style={{ color: accent.monthColor }}>{month}</div>
        </div>

        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            {/* Type chip */}
            {event.gathering_type && event.gathering_type !== 'other' && (
              <span
                className="rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{ background: 'rgba(12,24,38,0.05)', color: 'rgba(12,24,38,0.72)' }}
                title={typeLabel}
              >
                <span aria-hidden="true" className="mr-1">{typeIcon}</span>{typeLabel}
              </span>
            )}
            {isCancelled ? (
              <span className="rounded-full px-2.5 py-0.5 text-xs font-semibold"
                style={{ background: 'rgba(0,0,0,0.06)', color: '#94a3b8' }}>
                Cancelled
              </span>
            ) : archive ? (
              <span className="rounded-full px-2.5 py-0.5 text-xs font-semibold"
                style={{ background: 'rgba(21,36,54,0.06)', color: '#334155' }}>
                Past Gathering
              </span>
            ) : (
              <span
                className="rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{ background: accent.pillBg, color: accent.pillColor }}
              >
                {locationLabel}
              </span>
            )}
            {access.value !== 'included_with_collective' && (
              <span
                className="rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{
                  background: access.value === 'paid_separately' ? 'rgba(212,176,72,0.14)'
                    : access.value === 'invitation_only' ? 'rgba(126,66,145,0.14)'
                    : 'rgba(56,160,158,0.10)',
                  color: access.value === 'paid_separately' ? '#8A6A15'
                    : access.value === 'invitation_only' ? '#6B2C7A'
                    : '#0f766e',
                }}
              >
                {access.short}
                {access.value === 'paid_separately'
                  && event.ticket_price_cents != null
                  && event.ticket_currency
                  && ` \u00b7 ${formatMoneyCents(event.ticket_price_cents, event.ticket_currency)}`}
              </span>
            )}
            {/* Countdown — the small gentle anticipation pill */}
            {showCountdown && (
              <span
                className={[
                  'rounded-full px-2.5 py-0.5 text-xs font-semibold',
                  isLive ? 'animate-pulse' : '',
                ].join(' ')}
                style={
                  isLive
                    ? { background: 'rgba(22,163,74,0.10)', color: '#15803d' }
                    : { background: 'rgba(12,24,38,0.05)', color: 'rgba(12,24,38,0.62)' }
                }
              >
                {countdown}
              </span>
            )}
            <span className="text-xs text-black">{time}</span>
            {seriesLabel && (
              <span className="rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{ background: 'rgba(56,160,158,0.07)', color: '#38A09E' }}>
                {seriesLabel}
              </span>
            )}
          </div>

          <p className="font-medium text-navy-900 transition-colors group-hover:text-teal-700">
            {event.title}
          </p>
          {oneLine && (
            <p className="mt-1 line-clamp-1 text-sm leading-relaxed text-black">
              {oneLine}
            </p>
          )}

          {/* Second row — host + availability, calmly. Only shown
              when something meaningful is present so no zero-noise. */}
          {(event.host_name || placesLabel) && (
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-black">
              {event.host_name && (
                <span>Hosted by <span className="text-navy-700">{event.host_name}</span></span>
              )}
              {placesLabel && (
                <span
                  style={{ color: isFull ? '#94a3b8' : 'rgba(12,24,38,0.62)' }}
                >
                  {placesLabel}
                </span>
              )}
            </div>
          )}
        </div>

        <span className="shrink-0 self-center text-black transition-colors group-hover:text-teal-400">
          →
        </span>
      </Link>

      {/* Archive footer — calm CTA that reflects what's available */}
      {archive && (
        <div className="flex flex-wrap items-center gap-3 border-t px-5 py-3" style={{ borderColor: `${accent.border}22` }}>
          {event.recording_url ? (
            <a
              href={event.recording_url}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-lg px-4 py-1.5 text-xs font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              Watch replay →
            </a>
          ) : (
            <Link
              href={href}
              className="rounded-lg border border-slate-200 px-4 py-1.5 text-xs font-medium text-navy-700 transition-colors hover:border-navy-400 hover:bg-slate-50"
            >
              View Gathering
            </Link>
          )}
        </div>
      )}

      {/* Booking row */}
      {!archive && event.requires_booking && !isCancelled && (
        <div className="flex flex-wrap items-center gap-3 border-t px-5 py-3" style={{ borderColor: `${accent.border}22` }}>
          {isReserved ? (
            <>
              <span
                className="rounded-full px-2.5 py-0.5 text-xs font-semibold"
                style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}
              >
                You&rsquo;re in ✓
              </span>
              {event.can_cancel_booking && onCancelBooking && (
                <button
                  onClick={onCancelBooking}
                  className="text-xs text-black underline hover:text-slate-600"
                >
                  Release your place
                </button>
              )}
            </>
          ) : access.value === 'paid_separately' ? (
            /* Paid Gatherings: the purchase flow works for members AND
               non-members — check this branch BEFORE the !isMember
               fallback so a non-member sees Buy, not "Join to reserve". */
            !event.sales_enabled ? (
              <span className="text-xs italic" style={{ color: '#8A6A15' }}>
                Ticket sales aren&rsquo;t open yet
              </span>
            ) : event.spots_remaining !== null && event.spots_remaining <= 0 ? (
              <span className="text-xs text-black">Sold out</span>
            ) : (
              <Link
                href={`/spaces/${spaceSlug}/events/${event.id}`}
                className="rounded-lg px-4 py-1.5 text-xs font-semibold text-white transition-opacity hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                Buy your ticket
              </Link>
            )
          ) : !isMember ? (
            <Link
              href={`/spaces/${spaceSlug}/about`}
              className="text-xs font-medium text-teal-600 hover:underline"
            >
              Join to reserve →
            </Link>
          ) : isFull ? (
            <span className="text-xs text-black">All places taken</span>
          ) : bookingClosed ? (
            <span className="text-xs text-black">Places closed</span>
          ) : access.value === 'invitation_only' ? (
            <span className="text-xs italic" style={{ color: 'rgba(12,24,38,0.55)' }}>
              Invitation required
            </span>
          ) : event.can_book && onBook ? (
            <button
              onClick={onBook}
              className="rounded-lg px-4 py-1.5 text-xs font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              Reserve your place
            </button>
          ) : event.booking_note ? (
            <span className="text-xs text-black">{event.booking_note}</span>
          ) : null}

          {/* Bulk "reserve every session" — only meaningful for
              recurrence-tagged Gatherings that don't gate on a
              Series pass. Series-pass events already enforce weekly
              + total credit limits per-booking, and mixing "book all"
              with credit maths silently would produce surprising
              behaviour. Suppressed here to match the detail page. */}
          {event.recurrence_series_id
            && event.can_book
            && event.booking_access_type !== 'included_with_series'
            && onBookSeries && (
            <button
              onClick={onBookSeries}
              className="rounded-lg border border-teal-200 px-3 py-1.5 text-xs font-medium text-teal-700 transition-colors hover:bg-teal-50"
            >
              Reserve every Gathering in this series
            </button>
          )}
        </div>
      )}
    </div>
  )
}
