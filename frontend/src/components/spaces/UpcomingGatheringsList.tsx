import Link from 'next/link'
import type { EventSummary } from '@/types/platform'

/**
 * "This week" list rendered inside the Member Hub / Important panel.
 *
 * Auto-populated from the collective's upcoming Gatherings — no editable
 * content backs this section. See CollectiveSidebarPanel for the filter
 * (rolling 7-day window, active status).
 *
 * Intentionally minimal: one row per Gathering with day/date + time range
 * on line 1, title on line 2. Anything richer (description, location,
 * booking status) belongs on the Gatherings page, not this quick-glance
 * schedule.
 */

function timeParts(iso: string, timezone: string): { time: string; period: 'am' | 'pm' } {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).formatToParts(new Date(iso))
  const hour = parts.find(p => p.type === 'hour')?.value ?? ''
  const minute = parts.find(p => p.type === 'minute')?.value ?? ''
  const period = (parts.find(p => p.type === 'dayPeriod')?.value ?? '').toLowerCase() === 'am'
    ? 'am' as const
    : 'pm' as const
  return { time: `${hour}:${minute}`, period }
}

function formatTimeRange(startsAt: string, endsAt: string | null, timezone: string): string {
  const start = timeParts(startsAt, timezone)
  if (!endsAt) return `${start.time}${start.period}`
  const end = timeParts(endsAt, timezone)
  if (start.period === end.period) {
    return `${start.time}–${end.time}${end.period}`
  }
  return `${start.time}${start.period}–${end.time}${end.period}`
}

function formatDay(iso: string, timezone: string): string {
  const parts = new Intl.DateTimeFormat('en-AU', {
    timeZone: timezone,
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  }).formatToParts(new Date(iso))
  const weekday = parts.find(p => p.type === 'weekday')?.value ?? ''
  const day = parts.find(p => p.type === 'day')?.value ?? ''
  const month = parts.find(p => p.type === 'month')?.value ?? ''
  return `${weekday} ${day} ${month}`
}

interface Props {
  events: EventSummary[]
  timezone: string
  spaceSlug: string
}

export default function UpcomingGatheringsList({ events, timezone, spaceSlug }: Props) {
  if (events.length === 0) {
    return (
      <p className="text-[12px] leading-relaxed text-black italic">
        No sessions scheduled this week.
      </p>
    )
  }

  return (
    <ul className="flex flex-col gap-2">
      {events.map((event) => (
        <li key={event.id}>
          <Link
            href={`/spaces/${spaceSlug}/events/${event.id}`}
            className="block rounded-lg px-2.5 py-1.5 -mx-2.5 transition-colors hover:bg-black/[4%]"
          >
            <p className="text-[11.5px] text-black">
              {formatDay(event.starts_at, timezone)} • {formatTimeRange(event.starts_at, event.ends_at, timezone)}
            </p>
            <p className="mt-0.5 text-[13px] font-semibold leading-snug text-navy-900">
              {event.title}
            </p>
          </Link>
        </li>
      ))}
    </ul>
  )
}
