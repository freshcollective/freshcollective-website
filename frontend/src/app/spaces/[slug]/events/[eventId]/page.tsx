import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getSpace, getSpaceEvent } from '@/lib/serverApi'
import type { EventDetail } from '@/types/platform'
import { formatGatheringFullDate, formatGatheringTime } from '@/lib/dateTime'
import BookingPanel from '@/components/spaces/BookingPanel'

interface Props {
  params: Promise<{ slug: string; eventId: string }>
}

const LOCATION_LABEL: Record<string, string> = {
  zoom: 'Live — Zoom',
  in_person: 'In Person',
  async_recorded: 'Recorded Session',
}

type EventState = 'upcoming' | 'live' | 'past-replay' | 'past-no-replay'

function getEventState(event: EventDetail): EventState {
  const now = new Date()
  const start = new Date(event.starts_at)
  const end = event.ends_at
    ? new Date(event.ends_at)
    : new Date(start.getTime() + 60 * 60 * 1000)

  if (now < start) return 'upcoming'
  if (now >= start && now <= end) return 'live'
  return event.recording_url ? 'past-replay' : 'past-no-replay'
}


function formatDuration(startsAt: string, endsAt: string): string {
  const mins = Math.round(
    (new Date(endsAt).getTime() - new Date(startsAt).getTime()) / 60000,
  )
  if (mins < 60) return `${mins} min`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m > 0 ? `${h} hr ${m} min` : `${h} hr`
}

function calendarUrls(event: EventDetail) {
  const fmt = (d: Date) => d.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z'
  const start = new Date(event.starts_at)
  const end = event.ends_at
    ? new Date(event.ends_at)
    : new Date(start.getTime() + 60 * 60 * 1000)

  const googleParams = new URLSearchParams({
    action: 'TEMPLATE',
    text: event.title,
    dates: `${fmt(start)}/${fmt(end)}`,
    details: event.description ?? '',
    location: event.location_url ?? '',
  })
  const google = `https://calendar.google.com/calendar/render?${googleParams}`

  const outlookParams = new URLSearchParams({
    path: '/calendar/action/compose',
    rru: 'addevent',
    startdt: start.toISOString(),
    enddt: end.toISOString(),
    subject: event.title,
    body: event.description ?? '',
    location: event.location_url ?? '',
  })
  const outlook = `https://outlook.live.com/calendar/0/action/compose?${outlookParams}`

  return { google, outlook }
}

const STATE_BADGE: Record<EventState | 'cancelled', { label: string; bg: string; color: string }> = {
  upcoming:         { label: 'Upcoming',           bg: 'rgba(56,160,158,0.10)', color: '#0f766e' },
  live:             { label: 'Happening now',       bg: 'rgba(22,163,74,0.10)',  color: '#15803d' },
  'past-replay':    { label: 'Replay available',    bg: 'rgba(21,36,54,0.08)',   color: '#334155' },
  'past-no-replay': { label: 'Session ended',       bg: 'rgba(0,0,0,0.05)',      color: '#94a3b8' },
  'cancelled':      { label: 'Cancelled',           bg: 'rgba(239,68,68,0.08)',  color: '#b91c1c' },
}

export default async function EventDetailPage({ params }: Props) {
  const { slug, eventId } = await params
  const [space, event] = await Promise.all([
    getSpace(slug),
    getSpaceEvent(slug, eventId),
  ])

  if (!event) notFound()

  const timezone = space?.timezone ?? 'Australia/Melbourne'
  const formatFullDate = (iso: string) => formatGatheringFullDate(iso, timezone)
  const formatTime     = (iso: string) => formatGatheringTime(iso, timezone)

  const isCancelled = event.status === 'cancelled'
  const state = isCancelled ? 'cancelled' as const : getEventState(event)
  const badge = STATE_BADGE[state]
  const locationLabel = LOCATION_LABEL[event.location_type] ?? event.location_type
  const { google: googleCalUrl, outlook: outlookCalUrl } = calendarUrls(event)
  const icsUrl = `/api/spaces/${slug}/events/${eventId}/calendar.ics`

  return (
    <div className="max-w-3xl">

      {/* Back link */}
      <div className="mb-6">
        <Link
          href={`/spaces/${slug}/events`}
          className="text-sm text-slate-400 transition-colors hover:text-teal-600"
        >
          ← Gatherings
        </Link>
      </div>

      {/* ── Hero card ── */}
      <div
        className="relative mb-8 overflow-hidden rounded-2xl"
        style={{
          background: '#071824',
          border: '1px solid rgba(66,199,198,0.10)',
          boxShadow: '0 4px 24px rgba(7,24,36,0.18), 0 1px 4px rgba(0,0,0,0.10)',
        }}
      >
        {event.thumbnail_url && (
          <div className="relative h-52 w-full overflow-hidden">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={event.thumbnail_url}
              alt={event.title}
              className="h-full w-full object-cover"
            />
            {isCancelled && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/50">
                <span className="rounded-full bg-white/90 px-4 py-1.5 text-sm font-semibold text-slate-700">
                  Cancelled
                </span>
              </div>
            )}
          </div>
        )}
        <div className="px-7 py-8 md:px-9">
        <div
          className="mb-3 h-[2px] w-8 rounded-full"
          style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
        />

        {/* State badge */}
        <div className="mb-3">
          <span
            className={`inline-block rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-wide${state === 'live' ? ' animate-pulse' : ''}`}
            style={{ background: badge.bg, color: badge.color }}
          >
            {badge.label}
          </span>
        </div>

        <h1 className="mb-2 leading-snug">
          <span
            className="inline-block text-2xl font-semibold md:text-3xl"
            style={{
              background: 'linear-gradient(90deg, #55D7D2 0%, #D9FFFD 50%, #FFFFFF 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
          >
            {event.title}
          </span>
        </h1>

        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[13px]" style={{ color: 'rgba(255,255,255,0.60)' }}>
          <span>{locationLabel}</span>
          <span>{formatFullDate(event.starts_at)}</span>
          <span>{formatTime(event.starts_at)}</span>
          {event.ends_at && <span>{formatDuration(event.starts_at, event.ends_at)}</span>}
        </div>
        </div>
      </div>

      {/* ── Two-column layout: details + booking panel ── */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_260px] lg:items-start">

        {/* ── Left: details + actions ── */}
        <div className="flex flex-col gap-6">

          {/* Details card */}
          <div className="overflow-hidden rounded-2xl border border-border bg-white">
            <div className="border-b border-border px-5 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                Gathering details
              </p>
            </div>
            <div className="divide-y divide-border">
              {[
                { label: 'Date',     value: formatFullDate(event.starts_at) },
                { label: 'Time',     value: formatTime(event.starts_at) },
                { label: 'Format',   value: locationLabel },
                ...(event.ends_at
                  ? [{ label: 'Duration', value: formatDuration(event.starts_at, event.ends_at) }]
                  : []),
              ].map(({ label, value }) => (
                <div key={label} className="flex items-start gap-4 px-5 py-3">
                  <span className="w-20 shrink-0 text-[12px] font-medium text-slate-400">{label}</span>
                  <span className="text-[14px] text-navy-900">{value}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Description */}
          {event.description && (
            <div className="rounded-2xl border border-border bg-white px-6 py-5">
              <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                About this session
              </p>
              <div className="space-y-3">
                {event.description.split('\n').filter(Boolean).map((para: string, i: number) => (
                  <p key={i} className="text-[15px] leading-[1.8] text-slate-600">{para}</p>
                ))}
              </div>
            </div>
          )}

          {/* State-aware action buttons */}
          {state === 'upcoming' && (
            <div className="flex flex-wrap gap-3">
              {event.location_url && (
                <a
                  href={event.location_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center rounded-full bg-teal-600 px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-teal-700"
                >
                  Join session →
                </a>
              )}
              <a
                href={googleCalUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center rounded-full border border-slate-200 px-6 py-2.5 text-sm font-medium text-slate-600 transition-colors hover:border-slate-300 hover:text-navy-900"
              >
                Google Calendar
              </a>
              <a
                href={outlookCalUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center rounded-full border border-slate-200 px-6 py-2.5 text-sm font-medium text-slate-600 transition-colors hover:border-slate-300 hover:text-navy-900"
              >
                Outlook
              </a>
              <a
                href={icsUrl}
                download
                className="inline-flex items-center rounded-full border border-slate-200 px-6 py-2.5 text-sm font-medium text-slate-600 transition-colors hover:border-slate-300 hover:text-navy-900"
              >
                Download .ics
              </a>
            </div>
          )}

          {state === 'live' && (
            <div>
              {event.location_url ? (
                <a
                  href={event.location_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center rounded-full bg-teal-600 px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-teal-700"
                >
                  Join now →
                </a>
              ) : (
                <p className="text-sm text-slate-500">Join link will be available shortly.</p>
              )}
            </div>
          )}

          {state === 'past-replay' && event.recording_url && (
            <a
              href={event.recording_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center rounded-full bg-navy-900 px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-navy-800 w-fit"
            >
              Watch replay →
            </a>
          )}

          {state === 'past-no-replay' && (
            <p className="text-sm text-slate-400">
              A replay of this session will be available here once it has been processed.
            </p>
          )}

        </div>

        {/* ── Right: booking / info panel ── */}
        <div className="lg:sticky lg:top-6">
          <div
            className="rounded-2xl border bg-white p-5"
            style={{ borderColor: 'rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
          >
            <div
              className="mb-4 h-[2px] w-5 rounded-full"
              style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
            />

            {isCancelled ? (
              <>
                <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                  Status
                </p>
                <p className="text-[15px] font-semibold text-red-700">This event has been cancelled</p>
              </>
            ) : event.requires_booking ? (
              <BookingPanel
                eventId={event.id}
                spaceSlug={slug}
                requiresBooking={event.requires_booking}
                capacity={event.capacity}
                initialBookedCount={event.booked_count}
                initialSpotsRemaining={event.spots_remaining}
                bookingNote={event.booking_note}
                initialMyBookingStatus={event.my_booking_status as 'confirmed' | 'cancelled' | null}
                initialCanBook={event.can_book}
                initialCanCancelBooking={event.can_cancel_booking}
                isPast={state === 'past-replay' || state === 'past-no-replay'}
                recurrenceSeriesId={event.recurrence_series_id}
                accessType={event.booking_access_type}
                userHasPathwayAccess={event.user_has_pathway_access}
              />
            ) : (
              <>
                <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                  Access
                </p>
                <p className="mb-4 text-[15px] font-semibold text-navy-900">
                  {state === 'past-replay' || state === 'past-no-replay'
                    ? 'Session ended'
                    : 'Open to all members'}
                </p>
              </>
            )}

            {(state === 'upcoming' || state === 'live') && (
              <div className="mt-3 flex flex-col gap-1.5 text-center text-[12px]">
                <a href={googleCalUrl} target="_blank" rel="noopener noreferrer"
                  className="text-slate-400 transition-colors hover:text-teal-600">
                  Google Calendar
                </a>
                <a href={outlookCalUrl} target="_blank" rel="noopener noreferrer"
                  className="text-slate-400 transition-colors hover:text-teal-600">
                  Outlook
                </a>
                <a href={icsUrl} download
                  className="text-slate-400 transition-colors hover:text-teal-600">
                  Download .ics
                </a>
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  )
}
