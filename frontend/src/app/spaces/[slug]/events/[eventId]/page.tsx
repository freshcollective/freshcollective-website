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
  const d = new Date(isoString)
  return d.toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
  }) + ' UTC'
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

const STATE_BADGE: Record<EventState, { label: string; className: string }> = {
  upcoming: { label: 'Upcoming', className: 'bg-teal-50 text-teal-700' },
  live: { label: 'Happening now', className: 'bg-green-50 text-green-700 animate-pulse' },
  'past-replay': { label: 'Replay available', className: 'bg-navy-50 text-navy-600' },
  'past-no-replay': { label: 'Replay coming soon', className: 'bg-slate-50 text-slate-500' },
}

export default async function EventDetailPage({ params }: Props) {
  const { slug, eventId } = await params
  const event: EventDetail | null = await getSpaceEvent(slug, eventId)

  if (!event) notFound()

  const state = getEventState(event)
  const badge = STATE_BADGE[state]

  return (
    <div className="max-w-2xl">
      <Link
        href={`/spaces/${slug}/events`}
        className="mb-7 inline-block text-sm text-slate-400 hover:text-navy-700"
      >
        ← Live Experiences
      </Link>

      {/* State badge */}
      <div className="mb-5">
        <span className={`inline-block rounded-full px-3 py-1 text-xs font-medium ${badge.className}`}>
          {badge.label}
        </span>
      </div>

      {/* Header */}
      <div className="mb-8">
        <div className="mb-3 h-px w-6 bg-gold-500" />
        <h1 className="font-serif text-3xl leading-snug text-navy-900">{event.title}</h1>
      </div>

      {/* Date / time / location */}
      <div className="mb-8 flex flex-col gap-2 rounded-xl border border-border bg-surface px-6 py-5">
        <div className="flex items-start gap-3">
          <span className="w-20 shrink-0 text-xs font-medium uppercase tracking-wider text-slate-400">Date</span>
          <span className="text-sm text-navy-800">{formatFullDate(event.starts_at)}</span>
        </div>
        <div className="flex items-start gap-3">
          <span className="w-20 shrink-0 text-xs font-medium uppercase tracking-wider text-slate-400">Time</span>
          <span className="text-sm text-navy-800">{formatTime(event.starts_at)}</span>
        </div>
        <div className="flex items-start gap-3">
          <span className="w-20 shrink-0 text-xs font-medium uppercase tracking-wider text-slate-400">Format</span>
          <span className="text-sm text-navy-800">
            {LOCATION_LABEL[event.location_type] ?? event.location_type}
          </span>
        </div>
        {event.ends_at && (
          <div className="flex items-start gap-3">
            <span className="w-20 shrink-0 text-xs font-medium uppercase tracking-wider text-slate-400">Duration</span>
            <span className="text-sm text-navy-800">
              {Math.round((new Date(event.ends_at).getTime() - new Date(event.starts_at).getTime()) / 60000)} min
            </span>
          </div>
        )}
      </div>

      {/* Description */}
      {event.description && (
        <div className="mb-8">
          {event.description.split('\n').filter(Boolean).map((para, i) => (
            <p key={i} className="mb-3 text-[15px] leading-[1.8] text-slate-600">
              {para}
            </p>
          ))}
        </div>
      )}

      {/* State-aware actions */}
      <div className="flex flex-col gap-3">
        {state === 'upcoming' && (
          <>
            {event.location_url && (
              <a
                href={event.location_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block rounded-full bg-teal-500 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-teal-600 w-fit"
              >
                Join session →
              </a>
            )}
            <a
              href={googleCalendarUrl(event)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block rounded-full border border-navy-200 px-6 py-2.5 text-sm font-medium text-navy-600 transition-colors hover:border-navy-400 w-fit"
            >
              Add to Google Calendar
            </a>
          </>
        )}

        {state === 'live' && (
          <>
            {event.location_url ? (
              <a
                href={event.location_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block rounded-full bg-teal-500 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-teal-600 w-fit"
              >
                Join now →
              </a>
            ) : (
              <p className="text-sm text-slate-500">Join link will be available shortly.</p>
            )}
          </>
        )}

        {state === 'past-replay' && event.recording_url && (
          <a
            href={event.recording_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block rounded-full bg-navy-700 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-navy-800 w-fit"
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

      {/* Back to space */}
      <div className="mt-10 border-t border-border pt-6">
        <Link
          href={`/spaces/${slug}`}
          className="text-sm text-slate-400 hover:text-navy-700"
        >
          ← Back to Fresh Collective
        </Link>
      </div>
    </div>
  )
}
