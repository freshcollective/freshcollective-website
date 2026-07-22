import Link from 'next/link'
import { getCreatorEvents } from '@/lib/serverApi'
import type { CreatorEvent } from '@/types/platform'
import CreatorEventRow from './CreatorEventRow'

export default async function CreatorEventsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params

  // Two scoped fetches: `upcoming` drives the list; `archive` is
  // only needed to decide whether to expose the link. The `archive`
  // request is cheap for typical collectives (one indexed range
  // query) — no need to fetch every row twice.
  const [upcoming, past]: [CreatorEvent[], CreatorEvent[]] = await Promise.all([
    getCreatorEvents(slug, 'upcoming'),
    getCreatorEvents(slug, 'archive'),
  ])

  const hasArchive = past.length > 0
  const now = Date.now()
  const hasFutureCancelled = past.some((e) => {
    if (e.status !== 'cancelled') return false
    const endMs = e.ends_at
      ? Date.parse(e.ends_at)
      : Date.parse(e.starts_at) + 60 * 60 * 1000
    return endMs > now
  })
  const archiveLinkLabel = hasFutureCancelled ? 'Gathering archive' : 'Past Gatherings'

  return (
    <div>
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <div className="mb-2 h-px w-6 bg-gold-400" />
          <h1 className="font-serif text-2xl text-navy-900">Gatherings</h1>
          <p className="mt-1 text-sm text-black">
            {upcoming.length === 0
              ? 'None scheduled right now.'
              : `${upcoming.length} upcoming Gathering${upcoming.length !== 1 ? 's' : ''}`}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-4">
          {hasArchive && (
            <Link
              href={`/creator/spaces/${slug}/events/archive`}
              className="text-[13px] font-medium text-navy-700 underline-offset-4 transition-colors hover:text-teal-600 hover:underline"
            >
              {archiveLinkLabel}
            </Link>
          )}
          <Link
            href={`/creator/spaces/${slug}/events/new`}
            className="rounded-lg bg-navy-900 px-4 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            + Create Gathering
          </Link>
        </div>
      </div>

      {upcoming.length === 0 ? (
        <div className="rounded-2xl border border-border bg-surface px-8 py-12 text-center">
          <p className="mb-2 font-serif text-xl text-navy-800">
            You haven&rsquo;t scheduled any upcoming Gatherings yet.
          </p>
          <p className="mx-auto max-w-md text-[14px] leading-relaxed text-black">
            Create a Gathering to begin bringing people together.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {upcoming.map((event) => (
            <CreatorEventRow key={event.id} event={event} slug={slug} />
          ))}
        </div>
      )}

      {hasArchive && (
        <div className="mt-8 flex justify-center">
          <Link
            href={`/creator/spaces/${slug}/events/archive`}
            className="rounded-full px-4 py-2 text-[13px] font-medium transition-colors"
            style={{
              background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
              color: 'var(--fc-accent, #0f766e)',
            }}
          >
            View Gathering archive →
          </Link>
        </div>
      )}
    </div>
  )
}
