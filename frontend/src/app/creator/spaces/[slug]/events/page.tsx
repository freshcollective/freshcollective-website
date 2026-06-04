import Link from 'next/link'
import { getCreatorEvents } from '@/lib/serverApi'
import type { CreatorEvent } from '@/types/platform'

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const TYPE_LABELS: Record<string, string> = {
  zoom: 'Zoom',
  in_person: 'In person',
  async_recorded: 'Recorded',
}

export default async function CreatorEventsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const events: CreatorEvent[] = await getCreatorEvents(slug)

  const upcoming = events.filter((e) => new Date(e.starts_at) >= new Date())
  const past = events.filter((e) => new Date(e.starts_at) < new Date())

  return (
    <div>
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <div className="mb-2 h-px w-6 bg-gold-400" />
          <h1 className="font-serif text-2xl text-navy-900">Gatherings</h1>
          <p className="mt-1 text-sm text-slate-400">
            {events.length === 0 ? 'No gatherings yet.' : `${events.length} gathering${events.length !== 1 ? 's' : ''}`}
          </p>
        </div>
        <Link
          href={`/creator/spaces/${slug}/events/new`}
          className="shrink-0 rounded-lg bg-navy-900 px-4 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          + Schedule
        </Link>
      </div>

      {events.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface px-8 py-10 text-center">
          <p className="font-serif text-lg text-navy-700">No gatherings yet</p>
          <p className="mt-1 text-sm text-slate-400">Schedule a live session, circle, workshop, or community touchpoint.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-8">
          {upcoming.length > 0 && (
            <section>
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">Upcoming</p>
              <div className="flex flex-col gap-3">
                {upcoming.map((event) => (
                  <EventRow key={event.id} event={event} slug={slug} />
                ))}
              </div>
            </section>
          )}
          {past.length > 0 && (
            <section>
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">Past</p>
              <div className="flex flex-col gap-3">
                {past.map((event) => (
                  <EventRow key={event.id} event={event} slug={slug} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}

function EventRow({ event, slug }: { event: CreatorEvent; slug: string }) {
  const isCancelled = event.status === 'cancelled'
  return (
    <div className={[
      'flex items-center gap-4 rounded-xl border bg-surface px-5 py-4',
      isCancelled ? 'border-red-100 opacity-70' : 'border-border',
    ].join(' ')}>
      {event.thumbnail_url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={event.thumbnail_url}
          alt=""
          className="h-12 w-16 shrink-0 rounded-lg object-cover"
        />
      )}
      <div className="min-w-0 flex-1">
        <div className="mb-0.5 flex items-center gap-2">
          <p className="truncate font-medium text-navy-900">{event.title}</p>
          {isCancelled ? (
            <span className="shrink-0 rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-600">
              Cancelled
            </span>
          ) : !event.is_published ? (
            <span className="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs text-slate-400">
              Draft
            </span>
          ) : null}
        </div>
        <p className="text-xs text-slate-400">
          {formatDate(event.starts_at)} · {TYPE_LABELS[event.location_type] ?? event.location_type}
          {event.requires_booking && (
            <> · {event.booked_count}{event.capacity ? `/${event.capacity}` : ''} booked</>
          )}
          {event.recurrence_label && <> · {event.recurrence_label}</>}
        </p>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {event.recurrence_series_id && (
            <span className="rounded-full bg-teal-50 px-2 py-0.5 text-[10px] font-medium text-teal-700">
              Series{event.recurrence_index ? ` · ${event.recurrence_index}/${event.recurrence_total}` : ''}
            </span>
          )}
          {event.is_public && (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
              Public
            </span>
          )}
        </div>
      </div>
      <Link
        href={`/creator/spaces/${slug}/events/${event.id}`}
        className="shrink-0 rounded-lg border border-navy-200 px-3 py-1.5 text-xs font-medium text-navy-700 hover:border-navy-400 hover:bg-navy-50"
      >
        Edit
      </Link>
    </div>
  )
}
