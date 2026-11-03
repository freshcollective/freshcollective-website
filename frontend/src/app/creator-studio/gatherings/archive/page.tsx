import Link from 'next/link'
import {
  getActiveCreatorSpace,
  getCreatorEvents,
  getCreatorGatheringSeriesList,
  getCreatorSpace,
} from '@/lib/serverApi'
import type { CreatorEvent, CreatorGatheringSeriesSummary } from '@/types/platform'
import { collectiveTimezone } from '@/lib/collectiveTimezone'
import { parseServerDatetime } from '@/lib/dateTime'
import CreatorEventRow from '@/app/creator/spaces/[slug]/events/CreatorEventRow'
import SeriesCard from '@/components/creator/SeriesCard'
import { seriesOccurrenceCount, standaloneGatherings } from '@/lib/seriesArchive'

/**
 * Creator Studio → Gatherings archive.
 *
 * Everything that no longer belongs on the main schedule, in the two
 * groups the main page uses: Gathering Series first, then standalone
 * Gatherings. Each keeps its full management link, so a creator can
 * still review a finished term's sessions, bookings and attendance.
 *
 * Series were missing entirely — this page only ever fetched events,
 * so a completed or archived term had nowhere to appear and sat in the
 * Series band on Upcoming instead. And every occurrence of a finished
 * term was listed here individually, so a thirty-session term read as
 * thirty unrelated Gatherings. Both are presentation: no row is
 * changed, and nothing is archived by being looked at.
 */

export default async function GatheringsArchivePage() {
  const primarySpace = await getActiveCreatorSpace()
  const [allEvents, space, series] = primarySpace
    ? await Promise.all([
        getCreatorEvents(primarySpace.slug, 'archive') as Promise<CreatorEvent[]>,
        getCreatorSpace(primarySpace.slug) as Promise<{ timezone?: string | null } | null>,
        getCreatorGatheringSeriesList(primarySpace.slug, 'archive') as
          Promise<CreatorGatheringSeriesSummary[]>,
      ])
    : [[] as CreatorEvent[], null, [] as CreatorGatheringSeriesSummary[]]
  const timezone = collectiveTimezone(space)

  // Occurrences of a Series are reachable through the Series, so they
  // are not listed again here. The rule is shared with the Upcoming
  // page — see ``lib/seriesArchive`` for why ``recurrence_series_id``
  // alone does not hide a row.
  const events = standaloneGatherings(allEvents)
  const groupedCount = seriesOccurrenceCount(allEvents)
  const isEmpty = events.length === 0 && series.length === 0

  const now = Date.now()
  const hasFutureCancelled = events.some((e) => {
    if (e.status !== 'cancelled') return false
    // No start, no end — a dateless draft is never a future
    // cancellation, and `Date.parse(null)` is NaN.
    if (!e.starts_at) return false
    const endMs = e.ends_at
      ? parseServerDatetime(e.ends_at).getTime()
      : parseServerDatetime(e.starts_at).getTime() + 60 * 60 * 1000
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
          {isEmpty
            ? 'Nothing archived yet.'
            : supportingCopy
              ?? [
                series.length > 0
                  ? `${series.length} Series`
                  : null,
                events.length > 0
                  ? `${events.length} ${countLabel}${events.length !== 1 ? 's' : ''}`
                  : null,
              ].filter(Boolean).join(' · ') + ' — includes cancelled Gatherings.'}
        </p>
      </div>

      {!primarySpace ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="text-[14px] text-black">Set up a collective first — Gatherings live inside it.</p>
        </div>
      ) : isEmpty ? (
        <div className="rounded-2xl border border-border bg-surface px-8 py-12 text-center">
          <p className="mb-2 font-serif text-xl text-navy-800">
            There are no past Gatherings in this Collective yet.
          </p>
        </div>
      ) : (
        <>
          {series.length > 0 && (
            <section className="mb-8">
              <div className="mb-3 flex items-baseline justify-between">
                <h2 className="font-serif text-[16px] text-navy-900">
                  Gathering Series
                </h2>
                <span className="text-[12px] text-slate-500">
                  Completed and archived terms
                </span>
              </div>
              {/* Same card as the main Gatherings page, so a finished
                  term still reads as a Series rather than becoming a
                  different kind of thing in a different list. */}
              <ul className="grid gap-4 sm:grid-cols-2">
                {series.map((s) => (
                  <li key={s.id}>
                    <SeriesCard series={s} />
                  </li>
                ))}
              </ul>
            </section>
          )}

          {events.length > 0 && (
            <section>
              {series.length > 0 && (
                <div className="mb-3 flex items-baseline justify-between">
                  <h2 className="font-serif text-[16px] text-navy-900">
                    Standalone Gatherings
                  </h2>
                  {groupedCount > 0 && (
                    <span className="text-[12px] text-slate-500">
                      {groupedCount} more {groupedCount === 1 ? 'session' : 'sessions'}
                      {' '}inside the Series above
                    </span>
                  )}
                </div>
              )}
              <div className="flex flex-col gap-3">
                {events.map((event) => (
                  <CreatorEventRow
                    key={event.id}
                    event={event}
                    slug={primarySpace.slug}
                    timezone={timezone}
                    allowDuplicate
                  />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}
