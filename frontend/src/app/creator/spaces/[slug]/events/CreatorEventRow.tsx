import Link from 'next/link'
import type { CreatorEvent } from '@/types/platform'
import {
  gatheringIcon, gatheringLabel,
  attendanceFormatLabel,
  accessTypeMeta,
} from '@/lib/gatheringTypes'

/**
 * CreatorEventRow — the compact list row used on both the main
 * Creator Studio Gatherings page and its archive counterpart.
 *
 * Kept as a shared, presentation-only component so archive vs
 * current styling stays consistent, and the "Edit" affordance
 * always points at the same detail URL regardless of context.
 */

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-AU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Compact price for the list row. E.g. 2500 + 'AUD' → 'A$25'. */
function formatTicketPrice(cents: number, currency: string): string {
  const prefix =
    currency === 'AUD' ? 'A$'
    : currency === 'NZD' ? 'NZ$'
    : currency === 'CAD' ? 'C$'
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

export default function CreatorEventRow({ event, slug }: Props) {
  const isCancelled = event.status === 'cancelled'
  const access = accessTypeMeta(event.booking_access_type)
  const typeIcon = gatheringIcon(event.gathering_type)
  const typeLabel = gatheringLabel(event.gathering_type)
  const formatLabel = event.attendance_format
    ? attendanceFormatLabel(event.attendance_format)
    : event.location_type

  return (
    <div className={[
      'flex items-center gap-4 rounded-xl border bg-surface px-5 py-4',
      isCancelled ? 'border-red-100 opacity-70' : 'border-border',
    ].join(' ')}>
      {event.thumbnail_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={event.thumbnail_url}
          alt=""
          className="h-12 w-16 shrink-0 rounded-lg object-cover"
        />
      ) : (
        <div
          className="flex h-12 w-16 shrink-0 items-center justify-center rounded-lg text-2xl"
          style={{ background: 'rgba(56,160,158,0.08)' }}
          aria-hidden="true"
        >
          {typeIcon}
        </div>
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
        <p className="text-xs text-black">
          {formatDate(event.starts_at)} · {formatLabel}
          {event.requires_booking && (
            <> · {event.booked_count}{event.capacity ? `/${event.capacity}` : ''} reserved</>
          )}
          {event.recurrence_label && <> · {event.recurrence_label}</>}
        </p>
        <div className="mt-1 flex flex-wrap gap-1.5">
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
                && ` · ${formatTicketPrice(event.ticket_price_cents, event.ticket_currency)}`}
            </span>
          )}
          {access.value === 'paid_separately' && event.ticket_sales && !event.ticket_sales.sales_enabled && (
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{ background: 'rgba(212,176,72,0.14)', color: '#8A6A15' }}
            >
              Testing only
            </span>
          )}
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
