'use client'

import { useState } from 'react'
import Link from 'next/link'
import EventCard from '@/components/spaces/EventCard'
import type { EventSummary, SeriesBookingResult } from '@/types/platform'
import {
  gatheringDateKey,
  todayGatheringKey,
  formatGatheringTime,
  formatGatheringTimeShort,
  formatGatheringMobileDayLabel,
} from '@/lib/dateTime'
import { getGatheringAccent } from '@/lib/gatheringAccent'
import { apiUrl } from '@/lib/api'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const WEEKDAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  events: EventSummary[]
  spaceSlug: string
  timezone: string
  isMember?: boolean
}

export default function GatheringsView({ events: initialEvents, spaceSlug, timezone, isMember = true }: Props) {
  const [events, setEvents] = useState<EventSummary[]>(initialEvents)
  const [view, setView] = useState<'list' | 'calendar'>('list')
  const [seriesResult, setSeriesResult] = useState<(SeriesBookingResult & { seriesId: string }) | null>(null)

  // Calendar month state — start on current UTC month
  const [monthStart, setMonthStart] = useState<Date>(() => {
    const now = new Date()
    return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1))
  })

  const year  = monthStart.getUTCFullYear()
  const month = monthStart.getUTCMonth()

  const prevMonth = () => setMonthStart(new Date(Date.UTC(year, month - 1, 1)))
  const nextMonth = () => setMonthStart(new Date(Date.UTC(year, month + 1, 1)))

  // ---------------------------------------------------------------------------
  // Booking handlers
  // ---------------------------------------------------------------------------

  async function handleBook(eventId: string) {
    const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/events/${eventId}/book`), {
      method: 'POST',
      credentials: 'include',
    })
    if (!res.ok) return
    setEvents(prev =>
      prev.map(e =>
        e.id !== eventId ? e : {
          ...e,
          my_booking_status: 'confirmed',
          can_book: false,
          can_cancel_booking: true,
          booked_count: e.booked_count + 1,
          spots_remaining: e.spots_remaining !== null ? e.spots_remaining - 1 : null,
        }
      )
    )
  }

  async function handleCancelBooking(eventId: string) {
    const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/events/${eventId}/cancel-booking`), {
      method: 'POST',
      credentials: 'include',
    })
    if (!res.ok) return
    setEvents(prev =>
      prev.map(e =>
        e.id !== eventId ? e : {
          ...e,
          my_booking_status: 'cancelled',
          can_book: true,
          can_cancel_booking: false,
          booked_count: Math.max(0, e.booked_count - 1),
          spots_remaining: e.spots_remaining !== null ? e.spots_remaining + 1 : null,
        }
      )
    )
  }

  async function handleBookSeries(eventId: string, seriesId: string) {
    const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/events/series/${seriesId}/book`), {
      method: 'POST',
      credentials: 'include',
    })
    if (!res.ok) return
    const result: SeriesBookingResult = await res.json()
    setSeriesResult({ ...result, seriesId })
    // Mark all future series events as booked in local state
    setEvents(prev =>
      prev.map(e =>
        e.recurrence_series_id !== seriesId ? e : {
          ...e,
          my_booking_status: 'confirmed',
          can_book: false,
          can_cancel_booking: true,
        }
      )
    )
  }

  // ---------------------------------------------------------------------------
  // Sorting / grouping
  // ---------------------------------------------------------------------------

  const sortedEvents = [...events].sort(
    (a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime(),
  )

  const eventsByKey: Record<string, EventSummary[]> = {}
  for (const e of sortedEvents) {
    const k = gatheringDateKey(e.starts_at, timezone)
    ;(eventsByKey[k] ??= []).push(e)
  }

  const yearStr  = String(year).padStart(4, '0')
  const monthStr = String(month + 1).padStart(2, '0')
  const monthPrefix = `${yearStr}-${monthStr}`
  const eventsThisMonth = sortedEvents.filter(e =>
    gatheringDateKey(e.starts_at, timezone).startsWith(monthPrefix),
  )

  const daysInMonth  = new Date(Date.UTC(year, month + 1, 0)).getUTCDate()
  const firstWeekday = new Date(Date.UTC(year, month, 1)).getUTCDay()
  const today        = todayGatheringKey(timezone)

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div>

      {/* Series booking result toast */}
      {seriesResult && (
        <div
          className="mb-4 flex items-start justify-between rounded-xl px-5 py-3.5"
          style={{ background: 'rgba(56,160,158,0.08)', border: '1px solid rgba(56,160,158,0.2)' }}
        >
          <p className="text-sm text-teal-800">
            Booked {seriesResult.booked} session{seriesResult.booked !== 1 ? 's' : ''}.
            {seriesResult.skipped_full > 0 && ` ${seriesResult.skipped_full} full.`}
            {seriesResult.skipped_closed > 0 && ` ${seriesResult.skipped_closed} booking closed.`}
            {seriesResult.already_booked > 0 && ` ${seriesResult.already_booked} already booked.`}
          </p>
          <button
            onClick={() => setSeriesResult(null)}
            className="ml-4 shrink-0 text-xs text-slate-400 hover:text-slate-600"
          >
            ✕
          </button>
        </div>
      )}

      {/* ── View toggle ── */}
      <div className="mb-6">
        <div className="inline-flex rounded-full border border-border bg-white p-0.5">
          {(['list', 'calendar'] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={[
                'rounded-full px-5 py-1.5 text-sm font-medium transition-colors',
                view === v
                  ? 'bg-teal-600 text-white shadow-sm'
                  : 'text-slate-500 hover:text-navy-900',
              ].join(' ')}
            >
              {v === 'list' ? 'List' : 'Calendar'}
            </button>
          ))}
        </div>
      </div>

      {/* ── List view ── */}
      {view === 'list' && (
        sortedEvents.length > 0 ? (
          <div className="flex flex-col gap-3">
            {sortedEvents.map((e) => (
              <EventCard
                key={e.id}
                event={e}
                spaceSlug={spaceSlug}
                timezone={timezone}
                isMember={isMember}
                onBook={() => handleBook(e.id)}
                onCancelBooking={() => handleCancelBooking(e.id)}
                onBookSeries={e.recurrence_series_id
                  ? () => handleBookSeries(e.id, e.recurrence_series_id!)
                  : undefined
                }
              />
            ))}
          </div>
        ) : (
          <div className="rounded-2xl border border-teal-100 bg-white px-7 py-8">
            <p className="mb-1 text-lg font-semibold text-navy-900">No upcoming gatherings yet.</p>
            <p className="text-sm leading-relaxed text-slate-400">
              {isMember
                ? 'Live calls, workshops, and sessions will appear here when scheduled. Check back soon.'
                : 'Public sessions will appear here when scheduled.'}
            </p>
          </div>
        )
      )}

      {/* ── Calendar view ── */}
      {view === 'calendar' && (
        <div className="overflow-hidden rounded-2xl border border-border bg-white">

          {/* Month navigation */}
          <div className="flex items-center justify-between border-b border-border px-5 py-3">
            <button
              onClick={prevMonth}
              aria-label="Previous month"
              className="rounded-lg px-3 py-1.5 text-sm text-slate-400 transition-colors hover:bg-slate-50 hover:text-navy-900"
            >
              ←
            </button>
            <span className="text-[15px] font-semibold text-navy-900">
              {MONTH_NAMES[month]} {year}
            </span>
            <button
              onClick={nextMonth}
              aria-label="Next month"
              className="rounded-lg px-3 py-1.5 text-sm text-slate-400 transition-colors hover:bg-slate-50 hover:text-navy-900"
            >
              →
            </button>
          </div>

          {/* ── Desktop calendar grid (hidden on mobile) ── */}
          <div className="hidden sm:block">

            {/* Weekday headers */}
            <div className="grid grid-cols-7 border-b border-border bg-slate-50/60">
              {WEEKDAY_LABELS.map((d) => (
                <div
                  key={d}
                  className="py-2 text-center text-[11px] font-semibold uppercase tracking-wider text-slate-400"
                >
                  {d}
                </div>
              ))}
            </div>

            {/* Day cells */}
            <div className="grid grid-cols-7 gap-px bg-border">

              {Array.from({ length: firstWeekday }).map((_, i) => (
                <div key={`blank-${i}`} className="min-h-[120px] bg-slate-50/50" />
              ))}

              {Array.from({ length: daysInMonth }).map((_, i) => {
                const day     = i + 1
                const cellKey = `${yearStr}-${monthStr}-${String(day).padStart(2, '0')}`
                const isToday = cellKey === today
                const dayEvts = eventsByKey[cellKey] ?? []

                return (
                  <div key={day} className="min-h-[120px] bg-white p-1.5">
                    <div className="mb-1 flex justify-end pr-0.5">
                      <span
                        className={[
                          'flex h-6 w-6 items-center justify-center rounded-full text-[12px] font-medium',
                          isToday ? 'bg-teal-500 text-white' : 'text-slate-400',
                        ].join(' ')}
                      >
                        {day}
                      </span>
                    </div>

                    <div className="flex flex-col gap-0.5">
                      {dayEvts.map((e) => {
                        const accent = getGatheringAccent(e.location_type)
                        return (
                          <Link
                            key={e.id}
                            href={`/spaces/${spaceSlug}/events/${e.id}`}
                            title={e.title}
                            className="block truncate rounded px-1.5 py-0.5 text-[10px] font-medium leading-tight transition-opacity hover:opacity-75"
                            style={{ background: accent.chipBg, color: accent.chipColor }}
                          >
                            {formatGatheringTimeShort(e.starts_at, timezone)} {e.title}
                          </Link>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>

            {eventsThisMonth.length === 0 && (
              <div className="border-t border-border px-5 py-6 text-center text-sm text-slate-400">
                No gatherings scheduled for this month.
              </div>
            )}
          </div>

          {/* ── Mobile: day-list for the month ── */}
          <div className="sm:hidden">
            {eventsThisMonth.length === 0 ? (
              <div className="px-5 py-8 text-center text-sm text-slate-400">
                No gatherings scheduled for this month.
              </div>
            ) : (
              <div className="divide-y divide-border">
                {Object.entries(
                  eventsThisMonth.reduce<Record<string, { iso: string; events: EventSummary[] }>>(
                    (acc, e) => {
                      const k = gatheringDateKey(e.starts_at, timezone)
                      if (!acc[k]) acc[k] = { iso: e.starts_at, events: [] }
                      acc[k].events.push(e)
                      return acc
                    },
                    {},
                  ),
                )
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([k, { iso, events: dayEvts }]) => (
                    <div key={k} className="px-5 py-4">
                      <p className="mb-2.5 text-[12px] font-semibold uppercase tracking-wider text-slate-400">
                        {formatGatheringMobileDayLabel(iso, timezone)}
                      </p>
                      <div className="flex flex-col gap-2">
                        {dayEvts.map((e) => (
                          <Link
                            key={e.id}
                            href={`/spaces/${spaceSlug}/events/${e.id}`}
                            className="flex items-center justify-between rounded-xl px-4 py-3 transition-opacity hover:opacity-80"
                            style={{ background: 'rgba(56,160,158,0.08)' }}
                          >
                            <div className="min-w-0">
                              <p className="truncate text-[14px] font-medium text-navy-900">{e.title}</p>
                              <p className="mt-0.5 text-[12px] text-slate-500">{formatGatheringTime(e.starts_at, timezone)}</p>
                            </div>
                            <span className="ml-3 shrink-0 text-teal-500">→</span>
                          </Link>
                        ))}
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>

        </div>
      )}
    </div>
  )
}
