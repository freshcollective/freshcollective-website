import Link from 'next/link'
import { getActiveCreatorSpace, getCreatorEvents } from '@/lib/serverApi'
import type { CreatorEvent } from '@/types/platform'
import CreatorEventRow from '@/app/creator/spaces/[slug]/events/CreatorEventRow'

/**
 * Creator Studio → Gatherings.
 *
 * Shows only current + upcoming active Gatherings. Everything past
 * and everything cancelled lives in the archive. This page never
 * groups client-side — the scoped API is the single source of truth.
 */

export default async function GatheringsPage() {
  const primarySpace = await getActiveCreatorSpace()

  // Two scoped fetches: `upcoming` drives the list, `archive` is
  // only used to decide whether to expose the archive link.
  const [upcoming, past]: [CreatorEvent[], CreatorEvent[]] = primarySpace
    ? await Promise.all([
        getCreatorEvents(primarySpace.slug, 'upcoming'),
        getCreatorEvents(primarySpace.slug, 'archive'),
      ])
    : [[], []]

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
          <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#000000' }}>
            Schedule live sessions, circles, workshops, or community touchpoints.
          </p>
        </div>
        {primarySpace && (
          <div className="mt-1 flex shrink-0 items-center gap-4">
            {hasArchive && (
              <Link
                href="/creator-studio/gatherings/archive"
                className="text-[13px] font-medium text-navy-700 underline-offset-4 transition-colors hover:text-teal-600 hover:underline"
              >
                {archiveLinkLabel}
              </Link>
            )}
            <Link
              href={`/creator/spaces/${primarySpace.slug}/events/new`}
              className="rounded-xl px-4 py-2 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
            >
              + Create Gathering
            </Link>
          </div>
        )}
      </div>

      {/* No collective yet */}
      {!primarySpace && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Set up your collective first, then create Gatherings within it.
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

      {/* Collective exists but no upcoming Gatherings */}
      {primarySpace && upcoming.length === 0 && (
        <div className="rounded-2xl border border-border bg-surface px-8 py-12 text-center">
          <p className="mb-2 font-serif text-xl text-navy-800">
            You haven&rsquo;t scheduled any upcoming Gatherings yet.
          </p>
          <p className="mx-auto max-w-md text-[14px] leading-relaxed text-black">
            Create a Gathering to begin bringing people together.
          </p>
        </div>
      )}

      {/* Upcoming list — no additional client-side grouping */}
      {primarySpace && upcoming.length > 0 && (
        <div className="flex flex-col gap-3">
          {upcoming.map((event) => (
            <CreatorEventRow key={event.id} event={event} slug={primarySpace.slug} />
          ))}
        </div>
      )}

      {/* Archive link — only when the archive has content */}
      {primarySpace && hasArchive && (
        <div className="mt-8 flex justify-center">
          <Link
            href="/creator-studio/gatherings/archive"
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
