import Link from 'next/link'
import { resolveMediaUrl } from '@/lib/api'
import type { EventSummary } from '@/types/platform'

/**
 * MemberGatheringsGrid — landing-page presentation.
 *
 * Follows the U1 information model:
 *   * ONE card per Gathering Series (Series children collapse
 *     inside their Series page — not shown as top-level cards).
 *   * ONE card per standalone Gathering (Events with no
 *     ``series_id``).
 *
 * Cards are Pathway-sibling in visual language (cover art +
 * hover shadow lift + status/date footer) but the two kinds
 * carry different metadata:
 *   * Series card         → date range, Gathering count,
 *                            "View Series →"
 *   * Standalone card     → date/time, format, booking state,
 *                            "View & reserve →"
 *
 * Nothing here calls any endpoints — the parent server page
 * hydrates and passes filtered data.
 */

interface SeriesAccessSummary {
  has_access: boolean
  option_name: string | null
}

interface SeriesSummary {
  id: string
  slug: string
  title: string
  description: string | null
  cover_image_url: string | null
  starts_at: string
  ends_at: string | null
  total_gathering_count: number
  upcoming_gathering_count: number
  has_purchasable_options: boolean
  access: SeriesAccessSummary
}

function formatDateRange(startsAt: string, endsAt: string | null): string {
  const start = new Date(startsAt).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
  if (!endsAt) return `Starts ${start} · Ongoing`
  const end = new Date(endsAt).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
  return `${start} – ${end}`
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-AU', {
    weekday: 'short', day: 'numeric', month: 'short',
    hour: 'numeric', minute: '2-digit',
  })
}

export default function MemberGatheringsGrid({
  spaceSlug, series, standaloneEvents,
}: {
  spaceSlug: string
  series: SeriesSummary[]
  standaloneEvents: EventSummary[]
}) {
  const hasAnything = series.length > 0 || standaloneEvents.length > 0
  if (!hasAnything) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
        <p className="font-serif text-lg text-navy-900">Nothing scheduled yet.</p>
        <p className="mt-2 text-[13px] leading-relaxed text-slate-600">
          When the Creator adds Gatherings or a Series, they'll appear here.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {series.length > 0 && (
        <section>
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="font-serif text-[17px] text-navy-900">Gathering Series</h2>
            <span className="text-[12px] text-slate-500">
              {series.length} Series
            </span>
          </div>
          <ul className="grid gap-4 sm:grid-cols-2">
            {series.map((s) => (
              <li key={s.id}>
                <SeriesCard spaceSlug={spaceSlug} series={s} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {standaloneEvents.length > 0 && (
        <section>
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="font-serif text-[17px] text-navy-900">Standalone Gatherings</h2>
            <span className="text-[12px] text-slate-500">
              {standaloneEvents.length} upcoming
            </span>
          </div>
          <ul className="grid gap-4 sm:grid-cols-2">
            {standaloneEvents.map((ev) => (
              <li key={ev.id}>
                <StandaloneCard spaceSlug={spaceSlug} event={ev} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Series card — Pathway-sibling visual language, Series metadata
// ---------------------------------------------------------------------------

function SeriesCard({
  spaceSlug, series,
}: {
  spaceSlug: string
  series: SeriesSummary
}) {
  const cover = resolveMediaUrl(series.cover_image_url ?? undefined)
  const dateRange = formatDateRange(series.starts_at, series.ends_at)
  const hasAccess = series.access.has_access
  const upcomingLabel = series.upcoming_gathering_count > 0
    ? `${series.upcoming_gathering_count} upcoming`
    : series.total_gathering_count > 0
      ? 'No upcoming Gatherings'
      : 'Coming soon'

  return (
    <Link
      href={`/spaces/${spaceSlug}/gathering-series/${series.slug}`}
      // Hover border tracks the Collective palette via
      // --fc-accent-line (defined by CollectiveThemeProvider). Falls
      // back to the platform teal only when no palette is active.
      className="group flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-white shadow-sm transition-all hover:-translate-y-1 hover:shadow-lg hover:border-[color:var(--fc-accent-line,rgba(56,160,158,0.24))]"
    >
      {cover ? (
        <div className="relative h-40 w-full overflow-hidden">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={cover} alt="" className="h-full w-full object-cover" />
          <div
            aria-hidden="true"
            className="absolute inset-0"
            style={{
              background: 'linear-gradient(to top, rgba(0,0,0,0.86) 0%, rgba(0,0,0,0.70) 22%, rgba(0,0,0,0.50) 46%, rgba(0,0,0,0.32) 72%, rgba(0,0,0,0.20) 100%)',
            }}
          />
          <span
            className="absolute bottom-3 left-3 inline-flex items-center rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-white"
            style={{ background: 'rgba(15,23,42,0.55)', backdropFilter: 'blur(2px)' }}
          >
            {dateRange}
          </span>
          {hasAccess && (
            <span
              className="absolute right-3 top-3 inline-flex items-center rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold"
              style={{
                background: 'var(--fc-accent, #0f766e)',
                color: 'var(--fc-accent-contrast, #FFFFFF)',
              }}
            >
              You&apos;re in
            </span>
          )}
        </div>
      ) : (
        // No-cover placeholder — soft Collective primary at 8%. On
        // The Grove this reads as warm rust; on EMBODY as sand/teal.
        <div
          className="relative h-28 w-full"
          style={{
            background:
              'linear-gradient(135deg, var(--fc-accent-soft, rgba(56,160,158,0.10)) 0%, var(--fc-accent-tint, rgba(56,160,158,0.06)) 100%)',
          }}
        >
          <div className="absolute inset-0 flex items-end p-4">
            <p
              className="text-[11.5px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--fc-accent, #0f766e)' }}
            >
              {dateRange}
            </p>
          </div>
          {hasAccess && (
            <span
              className="absolute right-3 top-3 inline-flex items-center rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold"
              style={{
                background: 'var(--fc-accent, #0f766e)',
                color: 'var(--fc-accent-contrast, #FFFFFF)',
              }}
            >
              You&apos;re in
            </span>
          )}
        </div>
      )}

      <div className="flex flex-1 flex-col p-4">
        <h3 className="font-serif text-[17px] leading-snug text-navy-900">{series.title}</h3>
        {series.description && (
          <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-slate-600">
            {series.description}
          </p>
        )}
        <div className="mt-auto flex items-center justify-between gap-3 border-t border-border pt-3">
          <span className="text-[12px] text-slate-500">{upcomingLabel}</span>
          <span
            className="text-[13px] font-semibold transition-opacity group-hover:opacity-80"
            style={{ color: 'var(--fc-accent, #0f766e)' }}
          >
            View Series →
          </span>
        </div>
      </div>
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Standalone Gathering card — same visual family, different metadata
// ---------------------------------------------------------------------------

function StandaloneCard({
  spaceSlug, event,
}: {
  spaceSlug: string
  event: EventSummary
}) {
  const cover = resolveMediaUrl(event.thumbnail_url ?? undefined)
  const isOnline = event.location_type !== 'in_person'
  const isPaid = event.booking_access_type === 'paid_separately'

  // Compact CTA state — matches the detail-page rules.
  //   Reserved  = palette-primary text (matches sidebar's reserved chip).
  //   Full      = neutral slate — semantic 'unavailable', not brand.
  //   Others    = palette-primary text ("View" / "View & buy").
  // The price pill retains a warm gold — deliberately kept off-palette
  // because it is a price, not a brand accent.
  let statusLabel = 'View Gathering →'
  let statusUsesPalette = true
  if (event.my_booking_status === 'confirmed') {
    statusLabel = 'Reserved'
    statusUsesPalette = true
  } else if (event.capacity != null && event.spots_remaining === 0) {
    statusLabel = 'Full'
    statusUsesPalette = false
  } else if (isPaid) {
    statusLabel = event.ticket_price_cents != null ? 'View & buy →' : 'View →'
  }

  return (
    <Link
      href={`/spaces/${spaceSlug}/events/${event.id}`}
      className="group flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-white shadow-sm transition-all hover:-translate-y-1 hover:shadow-lg hover:border-[color:var(--fc-accent-line,rgba(56,160,158,0.24))]"
    >
      {cover ? (
        <div className="relative h-40 w-full overflow-hidden">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={cover} alt="" className="h-full w-full object-cover" />
          <div
            aria-hidden="true"
            className="absolute inset-0"
            style={{
              background: 'linear-gradient(to top, rgba(0,0,0,0.86) 0%, rgba(0,0,0,0.70) 22%, rgba(0,0,0,0.50) 46%, rgba(0,0,0,0.32) 72%, rgba(0,0,0,0.20) 100%)',
            }}
          />
        </div>
      ) : (
        // No-cover placeholder — soft palette primary. Grove reads
        // warm rust; EMBODY reads sand/teal.
        <div
          className="h-24 w-full"
          style={{
            background:
              'linear-gradient(135deg, var(--fc-accent-soft, rgba(56,160,158,0.10)) 0%, var(--fc-accent-tint, rgba(56,160,158,0.06)) 100%)',
          }}
        />
      )}
      <div className="flex flex-1 flex-col p-4">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
          {formatDateTime(event.starts_at)} · {isOnline ? 'Online' : 'In person'}
        </p>
        <h3 className="mt-1 font-serif text-[16px] leading-snug text-navy-900">{event.title}</h3>
        {event.description && (
          <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-slate-600">
            {event.description}
          </p>
        )}
        <div className="mt-auto flex items-center justify-between gap-3 border-t border-border pt-3">
          {isPaid && event.ticket_price_cents != null ? (
            <span
              className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
              style={{ background: 'rgba(214,176,72,0.16)', color: '#8A6A15' }}
            >
              ${(event.ticket_price_cents / 100).toFixed(0)}
            </span>
          ) : (
            <span className="text-[12px] text-slate-500">
              {event.capacity != null
                ? `${event.booked_count}/${event.capacity} reserved`
                : 'Open to members'}
            </span>
          )}
          <span
            className="text-[13px] font-semibold transition-opacity group-hover:opacity-80"
            style={statusUsesPalette
              ? { color: 'var(--fc-accent, #0f766e)' }
              : { color: '#64748b' }}
          >
            {statusLabel}
          </span>
        </div>
      </div>
    </Link>
  )
}
