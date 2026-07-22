import Link from 'next/link'
import { getCreatorEvents } from '@/lib/serverApi'
import type { CreatorEvent } from '@/types/platform'
import CreatorEventRow from '../CreatorEventRow'

/**
 * Creator Studio → Gatherings archive.
 *
 * Newest-first list of past Gatherings. Each row keeps its Edit
 * link so caretakers can review attendance, resources, replay
 * settings or duplicate a past Gathering — exactly the same
 * management surface used from the main page.
 */

export default async function CreatorEventsArchivePage({
  params,
}: {
  params: Promise<{ slug: string }>
}) {
  const { slug } = await params
  const events: CreatorEvent[] = await getCreatorEvents(slug, 'archive')

  const now = Date.now()
  const hasFutureCancelled = events.some((e) => {
    if (e.status !== 'cancelled') return false
    const endMs = e.ends_at
      ? Date.parse(e.ends_at)
      : Date.parse(e.starts_at) + 60 * 60 * 1000
    return endMs > now
  })
  const title = hasFutureCancelled ? 'Gathering Archive' : 'Past Gatherings'
  const countLabel = hasFutureCancelled ? 'archived Gathering' : 'past Gathering'
  const supportingCopy = hasFutureCancelled
    ? 'Previous and cancelled Gatherings from this Collective.'
    : null

  return (
    <div>
      <div className="mb-8">
        <Link
          href={`/creator/spaces/${slug}/events`}
          className="mb-4 inline-block text-sm text-black transition-colors hover:text-teal-600"
        >
          ← Upcoming Gatherings
        </Link>
        <div className="mb-2 h-px w-6 bg-gold-400" />
        <h1 className="font-serif text-2xl text-navy-900">{title}</h1>
        <p className="mt-1 text-sm text-black">
          {events.length === 0
            ? 'Nothing archived yet.'
            : supportingCopy
              ?? `${events.length} ${countLabel}${events.length !== 1 ? 's' : ''}`}
        </p>
      </div>

      {events.length === 0 ? (
        <div className="rounded-2xl border border-border bg-surface px-8 py-12 text-center">
          <p className="mb-2 font-serif text-xl text-navy-800">
            There are no past Gatherings in this Collective yet.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {events.map((event) => (
            <CreatorEventRow key={event.id} event={event} slug={slug} />
          ))}
        </div>
      )}
    </div>
  )
}
