import Link from 'next/link'
import { resolveMediaUrl } from '@/lib/api'
import { formatCalendarDate } from '@/lib/dateTime'
import type { CreatorGatheringSeriesSummary } from '@/types/platform'
import { seriesLifecycleLabel, seriesLifecycleStyle } from '@/lib/seriesArchive'

/**
 * One Gathering Series, as a card.
 *
 * Extracted from ``GatheringSeriesBand`` so Archives presents a Series
 * the same way the main Gatherings page does. The alternative was a
 * second card design, which is how two lists of the same thing stop
 * looking like the same thing.
 *
 * A Server Component: it is a link and some text, and keeping it out
 * of the band's client bundle means the archive page needs no client
 * JavaScript at all.
 */

/** Human-readable date range. "Ongoing" when there is no end date, so
 *  a creator never reads a blank. */
export function seriesDateSummary(startsAt: string, endsAt: string | null): string {
  // ``formatCalendarDate``, not the instant path: a Series' dates are
  // CALENDAR days set from ``<input type="date">`` and stored as
  // ``…T00:00:00`` / ``…T23:59:59``. Converting 23:59:59 through a
  // timezone rolls a Series that ends 12 Dec into 13 Dec.
  const start = formatCalendarDate(startsAt)
  if (!endsAt) return `Starts ${start} · Ongoing`
  return `${start} – ${formatCalendarDate(endsAt)}`
}

export default function SeriesCard({
  series,
}: {
  series: CreatorGatheringSeriesSummary
}) {
  const cover = resolveMediaUrl(series.cover_image_url ?? undefined)
  const dateSummary = seriesDateSummary(series.starts_at, series.ends_at)
  // Falls back to the stored status for a caller that has not been
  // given a lifecycle — the field is derived at read time and older
  // callers of the list endpoint do not ask for it.
  const label = seriesLifecycleLabel(series.lifecycle ?? series.status)

  return (
    <Link
      href={`/creator-studio/gathering-series/${series.slug}`}
      className="group flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-white shadow-sm transition-all hover:-translate-y-1 hover:border-teal-200/60 hover:shadow-lg"
    >
      {cover ? (
        <div className="relative h-32 w-full overflow-hidden">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={cover} alt="" className="h-full w-full object-cover" />
          {/* Bottom-to-top gradient for legibility of the overlay pill. */}
          <div
            aria-hidden="true"
            className="absolute inset-0"
            style={{
              background:
                'linear-gradient(to top, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.10) 45%, rgba(0,0,0,0) 100%)',
            }}
          />
          <span
            className="absolute bottom-3 left-3 inline-flex items-center rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-white"
            style={{ background: 'rgba(15,23,42,0.55)', backdropFilter: 'blur(2px)' }}
          >
            {dateSummary}
          </span>
        </div>
      ) : (
        <div
          className="relative h-24 w-full"
          style={{
            background: 'linear-gradient(135deg, rgba(56,160,158,0.14) 0%, rgba(85,184,182,0.08) 100%)',
          }}
        >
          <div className="absolute inset-0 flex items-end p-4">
            <p
              className="text-[11.5px] font-semibold uppercase tracking-wider"
              style={{ color: '#0f766e' }}
            >
              {dateSummary}
            </p>
          </div>
        </div>
      )}

      <div className="flex flex-1 flex-col p-4">
        <div className="mb-3 flex items-start justify-between gap-2">
          <h3 className="font-serif text-[16px] leading-snug text-navy-900">
            {series.title}
          </h3>
          <span
            className="shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider"
            style={seriesLifecycleStyle(series.lifecycle ?? series.status)}
          >
            {label}
          </span>
        </div>
        <div className="mt-auto flex items-center justify-between gap-3 border-t border-border pt-3">
          <span className="text-[11.5px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
            {series.gathering_count} Gathering{series.gathering_count === 1 ? '' : 's'}
            {series.payment_option_count > 0 && (
              <> · {series.payment_option_count} Payment Option{series.payment_option_count === 1 ? '' : 's'}</>
            )}
          </span>
          <span className="text-[13px] font-semibold text-teal-700 transition-colors group-hover:text-teal-800">
            Open →
          </span>
        </div>
      </div>
    </Link>
  )
}
