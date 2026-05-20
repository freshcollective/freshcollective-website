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
}

export default function EventCard({ event, spaceSlug, timezone }: EventCardProps) {
  const { day, month, time } = formatGatheringDate(event.starts_at, timezone)
  const locationLabel = LOCATION_LABEL[event.location_type] ?? event.location_type
  const href = `/spaces/${spaceSlug}/events/${event.id}`
  const accent = getGatheringAccent(event.location_type)

  return (
    <Link
      href={href}
      className="group flex items-start gap-5 rounded-2xl border bg-white p-5 transition-all hover:-translate-y-0.5 hover:shadow-md"
      style={{
        borderColor: `${accent.border}33`,
        borderLeft: `3px solid ${accent.border}`,
      }}
    >
      {/* Date block */}
      <div className="shrink-0 text-center">
        <div className="text-2xl font-bold leading-none text-navy-900">{day}</div>
        <div className="mt-0.5 text-xs font-semibold uppercase tracking-wider" style={{ color: accent.monthColor }}>{month}</div>
      </div>

      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <span
            className="rounded-full px-2.5 py-0.5 text-xs font-medium"
            style={{ background: accent.pillBg, color: accent.pillColor }}
          >
            {locationLabel}
          </span>
          <span className="text-xs text-slate-400">{time}</span>
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
  )
}
