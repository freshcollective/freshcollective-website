import Link from 'next/link'
import type { EventSummary } from '@/types/platform'
import { formatGatheringDate } from '@/lib/dateTime'

const LOCATION_LABEL: Record<string, string> = {
  zoom: 'Live — Zoom',
  in_person: 'In Person',
  async_recorded: 'Recorded',
}

type AccentStyle = {
  border: string
  pillBg: string
  pillColor: string
  monthColor: string
}

function getGatheringAccent(locationType: string): AccentStyle {
  switch (locationType) {
    case 'zoom':
      return {
        border: '#38A09E',
        pillBg: 'rgba(56,160,158,0.10)',
        pillColor: '#0f766e',
        monthColor: '#0f766e',
      }
    case 'in_person':
      return {
        border: '#BF9830',
        pillBg: 'rgba(191,152,48,0.10)',
        pillColor: '#92700a',
        monthColor: '#92700a',
      }
    case 'async_recorded':
      return {
        border: '#334155',
        pillBg: 'rgba(51,65,85,0.08)',
        pillColor: '#334155',
        monthColor: '#475569',
      }
    default:
      return {
        border: '#94a3b8',
        pillBg: 'rgba(148,163,184,0.10)',
        pillColor: '#64748b',
        monthColor: '#64748b',
      }
  }
}

interface EventCardProps {
  event: EventSummary
  spaceSlug: string
}

export default function EventCard({ event, spaceSlug }: EventCardProps) {
  const { day, month, time } = formatGatheringDate(event.starts_at)
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
