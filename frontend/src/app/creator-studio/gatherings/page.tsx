import Link from 'next/link'
import { getActiveCreatorSpace, getCreatorEvents } from '@/lib/serverApi'
import type { CreatorEvent } from '@/types/platform'

const LOCATION_LABELS: Record<string, string> = {
  zoom: 'Zoom',
  in_person: 'In person',
  async_recorded: 'Recorded',
}

function GatheringRow({
  event,
  spaceSlug,
  isPast,
}: {
  event: CreatorEvent
  spaceSlug: string
  isPast?: boolean
}) {
  const isCancelled = event.status === 'cancelled'
  const day = new Date(event.starts_at).getDate()
  const month = new Date(event.starts_at).toLocaleDateString('en-GB', { month: 'short' })
  const time = new Date(event.starts_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })

  return (
    <div
      className="flex items-center gap-4 rounded-2xl border bg-white px-5 py-4 transition-all"
      style={{
        borderColor: isCancelled ? 'rgba(239,68,68,0.15)' : 'rgba(0,0,0,0.07)',
        opacity: isCancelled || isPast ? 0.7 : 1,
      }}
    >
      {/* Thumbnail or date block */}
      {event.thumbnail_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={event.thumbnail_url}
          alt=""
          className="h-12 w-16 shrink-0 rounded-xl object-cover"
        />
      ) : (
        <div
          className="shrink-0 rounded-xl p-2 text-center"
          style={{ background: 'rgba(56,160,158,0.08)', minWidth: '48px' }}
        >
          <p className="text-[18px] font-bold leading-none text-navy-900">{day}</p>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-teal-600">{month}</p>
        </div>
      )}

      {/* Main info */}
      <div className="min-w-0 flex-1">
        <div className="mb-0.5 flex flex-wrap items-center gap-2">
          <p className="truncate text-[15px] font-medium text-navy-900">{event.title}</p>
          {isCancelled && (
            <span className="shrink-0 rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-semibold text-red-600">
              Cancelled
            </span>
          )}
          {!isCancelled && !event.is_published && (
            <span
              className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{ background: 'rgba(212,176,72,0.12)', color: '#b08d2a' }}
            >
              Draft
            </span>
          )}
        </div>

        <p className="text-[12px] text-slate-400">
          {time} · {LOCATION_LABELS[event.location_type] ?? event.location_type}
        </p>

        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {event.requires_booking && (
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}
            >
              {event.booked_count}{event.capacity ? `/${event.capacity}` : ''} booked
            </span>
          )}
          {isPast && event.attended_count > 0 && (
            <span className="rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{ background: 'rgba(56,160,158,0.08)', color: '#0f766e' }}>
              {event.attended_count} attended
            </span>
          )}
          {isPast && event.no_show_count > 0 && (
            <span className="rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{ background: 'rgba(239,68,68,0.06)', color: '#b91c1c' }}>
              {event.no_show_count} no show
            </span>
          )}
          {event.recurrence_series_id && (
            <span className="rounded-full bg-teal-50 px-2 py-0.5 text-[10px] font-medium text-teal-700">
              Series{event.recurrence_index ? ` · ${event.recurrence_index}/${event.recurrence_total}` : ''}
            </span>
          )}
          {event.is_public && (
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{ background: 'rgba(214,177,63,0.10)', color: '#7A5A00' }}
            >
              Public preview
            </span>
          )}
        </div>
      </div>

      {/* Edit action */}
      <Link
        href={`/creator/spaces/${spaceSlug}/events/${event.id}`}
        className="shrink-0 rounded-xl border border-border px-3 py-1.5 text-[12px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
      >
        Edit
      </Link>
    </div>
  )
}

export default async function GatheringsPage() {
  const primarySpace = await getActiveCreatorSpace()
  const events: CreatorEvent[] = primarySpace ? await getCreatorEvents(primarySpace.slug) : []

  const now = new Date()
  const upcoming = events.filter((e) => new Date(e.starts_at) >= now && e.status !== 'cancelled')
  const past = events.filter((e) => new Date(e.starts_at) < now && e.status !== 'cancelled')
  const cancelled = events.filter((e) => e.status === 'cancelled')

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <p
            className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: '#38A09E' }}
          >
            Creator Studio
          </p>
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Gatherings</h1>
          <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
            Schedule live sessions, circles, workshops, or community touchpoints.
          </p>
        </div>
        {primarySpace && (
          <div className="mt-1 shrink-0">
            <Link
              href={`/creator/spaces/${primarySpace.slug}/events/new`}
              className="rounded-xl px-4 py-2 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              + Schedule
            </Link>
          </div>
        )}
      </div>

      {/* No collective yet */}
      {!primarySpace && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-slate-500">
            Set up your collective first, then schedule gatherings within it.
          </p>
          <Link
            href="/creator-studio/create"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create collective
          </Link>
        </div>
      )}

      {/* Collective exists but no gatherings */}
      {primarySpace && events.length === 0 && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No gatherings scheduled.</p>
          <p className="mb-6 text-[14px] leading-relaxed text-slate-500">
            Add a live session, circle, workshop, Q&A, or community touchpoint.
          </p>
          <Link
            href={`/creator/spaces/${primarySpace.slug}/events/new`}
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Schedule gathering
          </Link>
        </div>
      )}

      {/* Upcoming */}
      {upcoming.length > 0 && (
        <section className="mb-8">
          <p
            className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: '#38A09E' }}
          >
            Upcoming
          </p>
          <div className="space-y-2">
            {upcoming.map((event) => (
              <GatheringRow key={event.id} event={event} spaceSlug={primarySpace!.slug} />
            ))}
          </div>
        </section>
      )}

      {/* Past */}
      {past.length > 0 && (
        <section className="mb-8">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
            Past
          </p>
          <div className="space-y-2">
            {past.slice(0, 8).map((event) => (
              <GatheringRow key={event.id} event={event} spaceSlug={primarySpace!.slug} isPast />
            ))}
            {past.length > 8 && (
              <p className="pt-1 text-center text-[12px] text-slate-400">
                + {past.length - 8} older session{past.length - 8 !== 1 ? 's' : ''}
              </p>
            )}
          </div>
        </section>
      )}

      {/* Cancelled */}
      {cancelled.length > 0 && (
        <section>
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-300">
            Cancelled
          </p>
          <div className="space-y-2">
            {cancelled.map((event) => (
              <GatheringRow key={event.id} event={event} spaceSlug={primarySpace!.slug} />
            ))}
          </div>
        </section>
      )}

    </div>
  )
}
