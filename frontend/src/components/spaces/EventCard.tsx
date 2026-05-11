import type { EventSummary } from '@/types/platform'

const LOCATION_LABEL: Record<string, string> = {
  zoom: 'Live — Zoom',
  in_person: 'In Person',
  async_recorded: 'Recorded',
}

function formatEventDate(isoString: string): { day: string; month: string; time: string } {
  const d = new Date(isoString)
  return {
    day: d.toLocaleDateString('en-GB', { day: '2-digit' }),
    month: d.toLocaleDateString('en-GB', { month: 'short' }).toUpperCase(),
    time: d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }),
  }
}

export default function EventCard({ event }: { event: EventSummary }) {
  const { day, month, time } = formatEventDate(event.starts_at)
  const locationLabel = LOCATION_LABEL[event.location_type] ?? event.location_type

  return (
    <div className="flex items-start gap-5 rounded-xl border border-border bg-surface p-5">
      {/* Date block */}
      <div className="shrink-0 text-center">
        <div className="font-serif text-2xl leading-none text-navy-900">{day}</div>
        <div className="mt-0.5 text-xs font-medium uppercase tracking-wider text-gold-600">{month}</div>
      </div>

      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-teal-50 px-2.5 py-0.5 text-xs font-medium text-teal-700">
            {locationLabel}
          </span>
          <span className="text-xs text-slate-400">{time} UTC</span>
        </div>
        <p className="font-medium text-navy-900">{event.title}</p>
        {event.description && (
          <p className="mt-1 line-clamp-2 text-sm leading-relaxed text-slate-500">
            {event.description.split('\n')[0]}
          </p>
        )}
      </div>
    </div>
  )
}
