import Link from 'next/link'
import { getActiveCreatorSpace, getCreatorEvents } from '@/lib/serverApi'
import type { CreatorEvent } from '@/types/platform'

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

function EventCard({
  event,
  spaceSlug,
  isPast,
}: {
  event: CreatorEvent
  spaceSlug: string
  isPast?: boolean
}) {
  return (
    <Link
      href={`/creator/spaces/${spaceSlug}/events/${event.id}`}
      className="group flex items-start gap-4 rounded-xl border border-border bg-white p-5 transition-all hover:border-teal-200 hover:shadow-sm"
      style={{ opacity: isPast ? 0.65 : 1 }}
    >
      <div
        className="shrink-0 rounded-lg p-2 text-center"
        style={{ background: 'rgba(56,160,158,0.08)', minWidth: '48px' }}
      >
        <p className="text-[18px] font-bold leading-none text-navy-900">
          {new Date(event.starts_at).getDate()}
        </p>
        <p className="text-[10px] font-medium uppercase tracking-wide text-teal-600">
          {new Date(event.starts_at).toLocaleDateString('en-GB', { month: 'short' })}
        </p>
      </div>
      <div className="min-w-0 flex-1">
        <p className="font-medium text-navy-900 transition-colors group-hover:text-teal-700">
          {event.title}
        </p>
        <p className="mt-0.5 text-[12px] text-slate-400">
          {formatDate(event.starts_at)} · {formatTime(event.starts_at)}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <span
            className="rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide"
            style={{ background: 'rgba(0,0,0,0.05)', color: '#94a3b8' }}
          >
            {event.location_type.replace(/_/g, ' ')}
          </span>
          {!event.is_published && (
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide"
              style={{ background: 'rgba(212,176,72,0.12)', color: '#b08d2a' }}
            >
              Draft
            </span>
          )}
        </div>
      </div>
    </Link>
  )
}

export default async function GatheringsPage() {
  const primarySpace = await getActiveCreatorSpace()
  const events: CreatorEvent[] = primarySpace ? await getCreatorEvents(primarySpace.slug) : []

  const now = new Date()
  const upcoming = events.filter((e) => new Date(e.starts_at) >= now)
  const past = events.filter((e) => new Date(e.starts_at) < now)

  return (
    <div className="max-w-4xl px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <p
            className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: '#38A09E' }}
          >
            Creator Studio
          </p>
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Gatherings</h1>
        </div>
        {primarySpace && (
          <div className="flex shrink-0 items-center gap-3">
            <Link
              href={`/creator/spaces/${primarySpace.slug}/events/new`}
              className="rounded-lg px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              + Schedule
            </Link>
            {events.length > 0 && (
              <Link
                href={`/creator/spaces/${primarySpace.slug}/events`}
                className="rounded-lg border border-border bg-white px-4 py-2 text-[13px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
              >
                Manage →
              </Link>
            )}
          </div>
        )}
      </div>

      {/* No collective yet */}
      {!primarySpace && (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-1.5 font-serif text-base text-navy-900">No collective yet</p>
          <p className="mb-5 text-sm text-slate-400">
            Set up your collective first, then schedule gatherings within it.
          </p>
          <Link
            href="/creator-studio/create"
            className="inline-flex items-center rounded-lg px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create collective
          </Link>
        </div>
      )}

      {/* Collective exists but no gatherings */}
      {primarySpace && events.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-1.5 font-serif text-base text-navy-900">No gatherings scheduled.</p>
          <p className="mb-5 text-sm text-slate-400">
            Add a live session, circle, workshop, Q&A, or community touchpoint.
          </p>
          <Link
            href={`/creator/spaces/${primarySpace.slug}/events/new`}
            className="inline-flex items-center rounded-lg px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Schedule gathering
          </Link>
        </div>
      )}

      {upcoming.length > 0 && (
        <section className="mb-8">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
            Upcoming
          </p>
          <div className="space-y-3">
            {upcoming.map((event) => (
              <EventCard key={event.id} event={event} spaceSlug={primarySpace!.slug} />
            ))}
          </div>
        </section>
      )}

      {past.length > 0 && (
        <section>
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
            Past
          </p>
          <div className="space-y-3">
            {past.slice(0, 6).map((event) => (
              <EventCard key={event.id} event={event} spaceSlug={primarySpace!.slug} isPast />
            ))}
          </div>
        </section>
      )}

    </div>
  )
}
