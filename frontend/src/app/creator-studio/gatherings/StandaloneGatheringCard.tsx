import Link from 'next/link'
import type { CreatorEvent } from '@/types/platform'
import {
  gatheringIcon, gatheringLabel,
  attendanceFormatLabel,
  accessTypeMeta,
} from '@/lib/gatheringTypes'

/**
 * Card-style presentation of a standalone Gathering on the Creator
 * Studio Gatherings landing page.
 *
 * Sibling of ``PathwayCard`` in visual language — rounded-2xl,
 * hover shadow lift, cover / icon band, footer with status pill +
 * concise metadata. Does not borrow Pathway metadata; keeps
 * Gathering-specific fields (date+time, attendance format,
 * booking count, ticket badge).
 *
 * The compact ``CreatorEventRow`` remains the presentation used on
 * the Archive page and inside Series editors, where lists of many
 * child Gatherings should stay dense.
 */

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-AU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function fmtPrice(cents: number, currency: string): string {
  const prefix =
    currency === 'AUD' ? 'A$'
    : currency === 'NZD' ? 'NZ$'
    : currency === 'USD' ? '$'
    : currency === 'GBP' ? '£'
    : currency === 'EUR' ? '€'
    : ''
  const dollars = cents / 100
  return `${prefix}${dollars.toFixed(dollars % 1 === 0 ? 0 : 2)}`
}

interface Props {
  event: CreatorEvent
  slug: string
}

export default function StandaloneGatheringCard({ event, slug }: Props) {
  const isCancelled = event.status === 'cancelled'
  const isDraft = !event.is_published && !isCancelled
  const access = accessTypeMeta(event.booking_access_type)
  const typeIcon = gatheringIcon(event.gathering_type)
  const typeLabel = gatheringLabel(event.gathering_type)
  const formatLabel = event.attendance_format
    ? attendanceFormatLabel(event.attendance_format)
    : event.location_type

  const editHref = `/creator/spaces/${slug}/events/${event.id}`

  return (
    <Link
      href={editHref}
      className={`group flex h-full flex-col overflow-hidden rounded-2xl border bg-white shadow-sm transition-all hover:-translate-y-1 hover:shadow-lg ${
        isCancelled ? 'border-red-100 opacity-70' : 'border-border hover:border-teal-200/60'
      }`}
    >
      {/* Cover / icon band — mirrors the visual role of PathwayCover. */}
      {event.thumbnail_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={event.thumbnail_url}
          alt=""
          className="h-32 w-full object-cover"
        />
      ) : (
        <div
          className="flex h-24 w-full items-center justify-center text-4xl"
          style={{ background: 'linear-gradient(135deg, rgba(56,160,158,0.14) 0%, rgba(85,184,182,0.08) 100%)' }}
          aria-hidden="true"
        >
          {typeIcon}
        </div>
      )}

      <div className="flex flex-1 flex-col p-4">
        <div className="mb-1 flex items-start justify-between gap-2">
          <h3 className="font-serif text-[15.5px] leading-snug text-navy-900">
            {event.title}
          </h3>
          {isCancelled && (
            <span className="shrink-0 rounded-full bg-red-50 px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-red-600">
              Cancelled
            </span>
          )}
          {isDraft && (
            <span className="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
              Draft
            </span>
          )}
        </div>

        <p className="text-[12.5px] text-black">
          {fmtDate(event.starts_at)}
        </p>
        <p className="mt-0.5 text-[11.5px] text-slate-500">
          {formatLabel}
          {event.requires_booking && (
            <> · {event.booked_count}{event.capacity ? `/${event.capacity}` : ''} reserved</>
          )}
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border pt-3">
          {event.gathering_type && event.gathering_type !== 'other' && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-700">
              {typeLabel}
            </span>
          )}
          {access.value !== 'included_with_collective' && (
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{
                background: access.value === 'paid_separately' ? 'rgba(212,176,72,0.16)'
                  : access.value === 'invitation_only' ? 'rgba(126,66,145,0.14)'
                  : 'rgba(56,160,158,0.10)',
                color: access.value === 'paid_separately' ? '#8A6A15'
                  : access.value === 'invitation_only' ? '#6B2C7A'
                  : '#0f766e',
              }}
            >
              {access.short}
              {access.value === 'paid_separately'
                && event.ticket_price_cents != null
                && event.ticket_currency
                && ` · ${fmtPrice(event.ticket_price_cents, event.ticket_currency)}`}
            </span>
          )}
          <span className="ml-auto text-[12.5px] font-semibold text-teal-700 transition-colors group-hover:text-teal-800">
            Edit →
          </span>
        </div>
      </div>
    </Link>
  )
}
