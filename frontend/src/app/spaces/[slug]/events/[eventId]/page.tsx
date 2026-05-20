// TODO (booking): RSVP / reserve-a-spot action — wire to booking endpoint
// TODO (booking): capacity limits per event (creator-managed in Creator Studio)
// TODO (booking): booking status — available, full, booked, cancelled
// TODO (booking): free bookings flow (RSVP with no payment)
// TODO (booking): paid bookings — route to checkout, integrate Stripe
// TODO (booking): attendee list visible to creator in Creator Studio
// TODO (booking): booking confirmation email + reminder notifications
// TODO (booking): per-event booking settings (open / invite-only / closed)

import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getSpaceEvent } from '@/lib/serverApi'
import type { EventDetail } from '@/types/platform'

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

function formatFullDate(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

function formatTime(isoString: string): string {
  return new Date(isoString).toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
  }) + ' UTC'
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

function googleCalendarUrl(event: EventDetail): string {
  const fmt = (d: Date) => d.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z'
  const start = new Date(event.starts_at)
  const end = event.ends_at
    ? new Date(event.ends_at)
    : new Date(start.getTime() + 60 * 60 * 1000)
  const params = new URLSearchParams({
    action: 'TEMPLATE',
    text: event.title,
    dates: `${fmt(start)}/${fmt(end)}`,
    details: event.description ?? '',
    location: event.location_url ?? '',
  })
  return `https://calendar.google.com/calendar/render?${params}`
}

const STATE_BADGE: Record<EventState, { label: string; bg: string; color: string }> = {
  upcoming:         { label: 'Upcoming',           bg: 'rgba(56,160,158,0.10)', color: '#0f766e' },
  live:             { label: 'Happening now',       bg: 'rgba(22,163,74,0.10)',  color: '#15803d' },
  'past-replay':    { label: 'Replay available',    bg: 'rgba(21,36,54,0.08)',   color: '#334155' },
  'past-no-replay': { label: 'Session ended',       bg: 'rgba(0,0,0,0.05)',      color: '#94a3b8' },
}

export default async function EventDetailPage({ params }: Props) {
  const { slug, eventId } = await params
  const event: EventDetail | null = await getSpaceEvent(slug, eventId)

  if (!event) notFound()

  const state = getEventState(event)
  const badge = STATE_BADGE[state]
  const locationLabel = LOCATION_LABEL[event.location_type] ?? event.location_type

  return (
    <div className="max-w-3xl">

      {/* Back link */}
      <div className="mb-6">
        <Link
          href={`/spaces/${slug}/events`}
          className="text-sm text-slate-400 transition-colors hover:text-teal-600"
        >
          ← Live Experiences
        </Link>
      </div>

      {/* ── Hero card ── */}
      <div
        className="relative mb-8 overflow-hidden rounded-2xl px-7 py-8 md:px-9"
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

      {/* ── Two-column layout: details + booking panel ── */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_260px] lg:items-start">

        {/* ── Left: details + actions ── */}
        <div className="flex flex-col gap-6">

          {/* Details card */}
          <div className="overflow-hidden rounded-2xl border border-border bg-white">
            <div className="border-b border-border px-5 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                Event details
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
                {event.description.split('\n').filter(Boolean).map((para, i) => (
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
                href={googleCalendarUrl(event)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center rounded-full border border-slate-200 px-6 py-2.5 text-sm font-medium text-slate-600 transition-colors hover:border-slate-300 hover:text-navy-900"
              >
                Add to Google Calendar
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

        {/* ── Right: booking panel ── */}
        {/* TODO (booking): replace this placeholder with real booking logic */}
        {/* TODO (booking): show "Reserve your spot" when booking is open */}
        {/* TODO (booking): show capacity remaining when limits are set */}
        {/* TODO (booking): show price or "Included with membership" */}
        {/* TODO (booking): disable/grey out when event is full or past */}
        <div className="lg:sticky lg:top-6">
          <div
            className="rounded-2xl border bg-white p-5"
            style={{ borderColor: 'rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
          >
            <div
              className="mb-4 h-[2px] w-5 rounded-full"
              style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
            />

            <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              Booking
            </p>
            <p className="mb-4 text-[15px] font-semibold text-navy-900">
              {state === 'past-replay' || state === 'past-no-replay'
                ? 'Session ended'
                : 'Booking not yet open'}
            </p>

            <div className="mb-4 space-y-2.5 text-[13px] text-slate-500">
              <div className="flex items-center justify-between">
                <span>Price</span>
                <span className="text-slate-400">—</span>
              </div>
              <div className="flex items-center justify-between">
                <span>Capacity</span>
                <span className="text-slate-400">—</span>
              </div>
            </div>

            <button
              disabled
              className="w-full rounded-xl bg-slate-100 py-2.5 text-sm font-semibold text-slate-400 cursor-not-allowed"
            >
              Booking coming soon
            </button>

            {(state === 'upcoming' || state === 'live') && (
              <a
                href={googleCalendarUrl(event)}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-3 block text-center text-[12px] text-slate-400 transition-colors hover:text-teal-600"
              >
                Add to Google Calendar
              </a>
            )}
          </div>
        </div>

      </div>
    </div>
  )
}
