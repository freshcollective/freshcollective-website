'use client'

import { useState } from 'react'
import Link from 'next/link'
import EventCard from '@/components/spaces/EventCard'
import type { EventSummary } from '@/types/platform'
import {
  gatheringDateKey,
  todayGatheringKey,
  formatGatheringTime,
  formatGatheringTimeShort,
  formatGatheringMobileDayLabel,
} from '@/lib/dateTime'

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
}

export default function GatheringsView({ events, spaceSlug, timezone }: Props) {
  const [view, setView] = useState<'list' | 'calendar'>('list')

  // Calendar month state — start on current UTC month (UTC and +10/+11 months align at boundaries)
  const [monthStart, setMonthStart] = useState<Date>(() => {
    const now = new Date()
    return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1))
  })

  const year  = monthStart.getUTCFullYear()
  const month = monthStart.getUTCMonth()

  const prevMonth = () => setMonthStart(new Date(Date.UTC(year, month - 1, 1)))
  const nextMonth = () => setMonthStart(new Date(Date.UTC(year, month + 1, 1)))

  // Sort all events ascending
  const sortedEvents = [...events].sort(
    (a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime(),
  )

  // Group events by collective local date key
  const eventsByKey: Record<string, EventSummary[]> = {}
  for (const e of sortedEvents) {
    const k = gatheringDateKey(e.starts_at, timezone)
    ;(eventsByKey[k] ??= []).push(e)
  }

  // Events that fall in the currently displayed month (collective local date)
  const yearStr  = String(year).padStart(4, '0')
  const monthStr = String(month + 1).padStart(2, '0')
  const monthPrefix = `${yearStr}-${monthStr}`
  const eventsThisMonth = sortedEvents.filter(e =>
    gatheringDateKey(e.starts_at, timezone).startsWith(monthPrefix),
  )

  // Calendar grid geometry
  const daysInMonth  = new Date(Date.UTC(year, month + 1, 0)).getUTCDate()
  const firstWeekday = new Date(Date.UTC(year, month, 1)).getUTCDay() // 0 = Sun
  const today        = todayGatheringKey(timezone)

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div>

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
              <EventCard key={e.id} event={e} spaceSlug={spaceSlug} timezone={timezone} />
            ))}
          </div>
        ) : (
          <div className="rounded-2xl border border-teal-100 bg-white px-7 py-8">
            <p className="mb-1 text-lg font-semibold text-navy-900">No upcoming gatherings yet.</p>
            <p className="text-sm leading-relaxed text-slate-400">
              Live calls, workshops, and sessions will appear here when scheduled. Check back soon.
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

            {/* Day cells — gap-px + bg-border gives crisp 1px separators */}
            <div className="grid grid-cols-7 gap-px bg-border">

              {/* Blank offset cells */}
              {Array.from({ length: firstWeekday }).map((_, i) => (
                <div key={`blank-${i}`} className="min-h-[120px] bg-slate-50/50" />
              ))}

              {/* Day cells */}
              {Array.from({ length: daysInMonth }).map((_, i) => {
                const day     = i + 1
                const cellKey = `${yearStr}-${monthStr}-${String(day).padStart(2, '0')}`
                const isToday = cellKey === today
                const dayEvts = eventsByKey[cellKey] ?? []

                return (
                  <div key={day} className="min-h-[120px] bg-white p-1.5">
                    {/* Day number */}
                    <div className="mb-1 flex justify-end pr-0.5">
                      <span
                        className={[
                          'flex h-6 w-6 items-center justify-center rounded-full text-[12px] font-medium',
                          isToday
                            ? 'bg-teal-500 text-white'
                            : 'text-slate-400',
                        ].join(' ')}
                      >
                        {day}
                      </span>
                    </div>

                    {/* Event chips */}
                    <div className="flex flex-col gap-0.5">
                      {dayEvts.map((e) => (
                        <Link
                          key={e.id}
                          href={`/spaces/${spaceSlug}/events/${e.id}`}
                          title={e.title}
                          className="block truncate rounded px-1.5 py-0.5 text-[10px] font-medium leading-tight transition-opacity hover:opacity-75"
                          style={{ background: 'rgba(56,160,158,0.12)', color: '#0f766e' }}
                        >
                          {formatGatheringTimeShort(e.starts_at, timezone)} {e.title}
                        </Link>
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Desktop empty-month note */}
            {eventsThisMonth.length === 0 && (
              <div className="border-t border-border px-5 py-6 text-center text-sm text-slate-400">
                No gatherings scheduled for this month.
              </div>
            )}
          </div>

          {/* ── Mobile: day-list for the month (hidden on sm+) ── */}
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
