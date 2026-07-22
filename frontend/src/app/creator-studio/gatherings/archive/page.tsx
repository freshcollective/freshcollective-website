import Link from 'next/link'
import { getActiveCreatorSpace, getCreatorEvents } from '@/lib/serverApi'
import type { CreatorEvent } from '@/types/platform'
import CreatorEventRow from '@/app/creator/spaces/[slug]/events/CreatorEventRow'

/**
 * Creator Studio → Gatherings archive.
 *
 * Contains every Gathering that no longer belongs on the main
 * schedule: past by end-time or cancelled at any time. Ordered
 * newest first. Each row keeps its full Manage link so caretakers
 * can review attendance, resources, replay settings or duplicate
 * a past Gathering — same management surface as the main page.
 */

export default async function GatheringsArchivePage() {
  const primarySpace = await getActiveCreatorSpace()
  const events: CreatorEvent[] = primarySpace
    ? await getCreatorEvents(primarySpace.slug, 'archive')
    : []

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
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8">
        <Link
          href="/creator-studio/gatherings"
          className="mb-4 inline-block text-sm text-black transition-colors hover:text-teal-600"
        >
          ← Upcoming Gatherings
        </Link>
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">{title}</h1>
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#000000' }}>
          {events.length === 0
            ? 'Nothing archived yet.'
            : supportingCopy
              ?? `${events.length} ${countLabel}${events.length !== 1 ? 's' : ''} — includes cancelled Gatherings.`}
        </p>
      </div>

      {!primarySpace ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="text-[14px] text-black">Set up a collective first — Gatherings live inside it.</p>
        </div>
      ) : events.length === 0 ? (
        <div className="rounded-2xl border border-border bg-surface px-8 py-12 text-center">
          <p className="mb-2 font-serif text-xl text-navy-800">
            There are no past Gatherings in this Collective yet.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {events.map((event) => (
            <CreatorEventRow key={event.id} event={event} slug={primarySpace.slug} />
          ))}
        </div>
      )}
    </div>
  )
}
