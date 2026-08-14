'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import {
  paletteHex,
  rgbaFromHex,
  type CollectivePaletteMeta,
} from '@/lib/collectivePalette'

/**
 * Compact schedule for a Gathering Series — Calendar | List toggle.
 *
 * Design intent:
 *   * A 20–30 session Series must not produce an endless scroll.
 *   * Calendar view is the desktop default; List remains the phone
 *     default (a seven-column month grid on a phone reads as a
 *     smudge, so the mobile branch renders a chronological list
 *     even when Calendar is toggled).
 *   * The Schedule is deliberately navigation-only. Clicking a
 *     session opens the existing Gathering detail page — the
 *     reservation UX + all backend guards live there unchanged.
 *
 * Session states rendered on chips:
 *     reserved         — the viewer is confirmed on this Gathering
 *     available        — viewer can reserve (has access; not full)
 *     access required  — Series-pass gate on the session
 *     full             — capacity reached
 *     past             — before now
 *
 * State colouring uses the Collective palette's primary hex for
 * the "reserved" accent so the Schedule feels branded to the
 * Collective, with neutral slate for the informational states.
 */

export interface SeriesScheduleGathering {
  id: string
  title: string
  starts_at: string
  ends_at: string | null
  attendance_format: string | null
  location_type: string
  venue_locality: string | null
  capacity: number | null
  booked_count: number
  spots_remaining: number | null
  booking_access_type: string
  my_booking_status: string | null
  is_past: boolean
}

type ScheduleView = 'calendar' | 'list'

type SessionState = 'reserved' | 'available' | 'access-required' | 'full' | 'past'

const WEEKDAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

function sessionState(
  g: SeriesScheduleGathering, memberHasSeriesAccess: boolean,
): SessionState {
  if (g.is_past) return 'past'
  if (g.my_booking_status === 'confirmed') return 'reserved'
  if (g.capacity != null && g.spots_remaining === 0) return 'full'
  if (g.booking_access_type === 'included_with_series' && !memberHasSeriesAccess) {
    return 'access-required'
  }
  return 'available'
}

function formatTimeShort(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString('en-AU', { hour: 'numeric', minute: '2-digit' }).toLowerCase()
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-AU', {
    weekday: 'short', day: 'numeric', month: 'short',
    hour: 'numeric', minute: '2-digit',
  })
}

function stateLabel(s: SessionState): string {
  switch (s) {
    case 'reserved':         return 'Reserved'
    case 'available':        return 'Reserve'
    case 'access-required':  return 'Access required'
    case 'full':             return 'Full'
    case 'past':             return 'Past'
  }
}

function stateChipStyles(
  s: SessionState, palette: CollectivePaletteMeta | null,
): { bg: string; color: string; ring: string | null } {
  const primary = paletteHex('primary', palette) ?? '#0f766e'
  switch (s) {
    case 'reserved':
      return {
        bg: rgbaFromHex(primary, 0.16),
        color: primary,
        ring: rgbaFromHex(primary, 0.32),
      }
    case 'available':
      return {
        bg: 'rgba(15,23,42,0.05)',
        color: '#0F172A',
        ring: 'rgba(15,23,42,0.10)',
      }
    case 'access-required':
      return { bg: 'rgba(214,177,63,0.14)', color: '#8A6A15', ring: 'rgba(214,177,63,0.30)' }
    case 'full':
      return { bg: 'rgba(148,163,184,0.16)', color: '#475569', ring: null }
    case 'past':
      return { bg: 'transparent', color: '#94A3B8', ring: null }
  }
}

/** Local ``YYYY-MM-DD`` key (avoids the UTC-shift bug that would
 *  smear a Sydney evening session into "tomorrow" in the grid). */
function localDayKey(iso: string): string {
  const d = new Date(iso)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** Best month to open on: today's month if the Series has upcoming
 *  sessions this month or later, otherwise the month of the first
 *  Series session (past or future). Falls back to today. */
function pickInitialMonth(upcoming: SeriesScheduleGathering[], past: SeriesScheduleGathering[]): Date {
  const now = new Date()
  if (upcoming.length > 0) {
    const first = new Date(upcoming[0].starts_at)
    return new Date(first.getFullYear(), first.getMonth(), 1)
  }
  if (past.length > 0) {
    const last = new Date(past[past.length - 1].starts_at)
    return new Date(last.getFullYear(), last.getMonth(), 1)
  }
  return new Date(now.getFullYear(), now.getMonth(), 1)
}

interface Props {
  spaceSlug: string
  upcoming: SeriesScheduleGathering[]
  past: SeriesScheduleGathering[]
  memberHasSeriesAccess: boolean
  palette: CollectivePaletteMeta | null
}

export default function SeriesSchedule({
  spaceSlug, upcoming, past, memberHasSeriesAccess, palette,
}: Props) {
  const [view, setView] = useState<ScheduleView>('calendar')
  const [monthStart, setMonthStart] = useState<Date>(() => pickInitialMonth(upcoming, past))

  const allSessions = useMemo(
    () => [...past, ...upcoming].sort(
      (a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime(),
    ),
    [past, upcoming],
  )

  // Bucket sessions by local YYYY-MM-DD for the calendar grid.
  const sessionsByDay = useMemo(() => {
    const m: Record<string, SeriesScheduleGathering[]> = {}
    for (const g of allSessions) {
      const k = localDayKey(g.starts_at)
      ;(m[k] ??= []).push(g)
    }
    return m
  }, [allSessions])

  const year = monthStart.getFullYear()
  const month = monthStart.getMonth()
  const firstWeekday = new Date(year, month, 1).getDay()
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const todayKey = localDayKey(new Date().toISOString())
  const prevMonth = () => setMonthStart(new Date(year, month - 1, 1))
  const nextMonth = () => setMonthStart(new Date(year, month + 1, 1))

  const totalCount = allSessions.length
  const upcomingCount = upcoming.length

  return (
    <section>
      {/* Section header + view toggle */}
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
            Schedule
          </p>
          <h2 className="mt-1 font-serif text-xl text-navy-900">
            {upcomingCount > 0
              ? `${upcomingCount} upcoming`
              : totalCount > 0
                ? 'No upcoming Gatherings'
                : 'No Gatherings yet'}
            {totalCount > upcomingCount && (
              <span className="ml-2 text-[13px] font-normal text-slate-500">
                · {totalCount - upcomingCount} past
              </span>
            )}
          </h2>
        </div>

        {totalCount > 0 && (
          <div
            role="tablist"
            aria-label="Schedule view"
            className="inline-flex rounded-full border border-border bg-white p-1"
          >
            <ViewToggleButton
              active={view === 'calendar'}
              onClick={() => setView('calendar')}
              label="Calendar"
            />
            <ViewToggleButton
              active={view === 'list'}
              onClick={() => setView('list')}
              label="List"
            />
          </div>
        )}
      </div>

      {totalCount === 0 && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-6 py-8 text-center text-[13px] italic text-slate-500">
          Gatherings will appear here as they are scheduled.
        </div>
      )}

      {totalCount > 0 && view === 'calendar' && (
        <>
          {/* Desktop calendar */}
          <div className="hidden overflow-hidden rounded-2xl border border-border bg-white sm:block">
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
              <button
                type="button" onClick={prevMonth}
                aria-label="Previous month"
                className="rounded-lg px-2.5 py-1 text-[13px] text-slate-500 transition-colors hover:bg-slate-50 hover:text-navy-900"
              >←</button>
              <span className="text-[14px] font-semibold text-navy-900">
                {MONTH_NAMES[month]} {year}
              </span>
              <button
                type="button" onClick={nextMonth}
                aria-label="Next month"
                className="rounded-lg px-2.5 py-1 text-[13px] text-slate-500 transition-colors hover:bg-slate-50 hover:text-navy-900"
              >→</button>
            </div>

            <div className="grid grid-cols-7 border-b border-border bg-slate-50/60">
              {WEEKDAY_LABELS.map((d) => (
                <div key={d} className="py-1.5 text-center text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">
                  {d}
                </div>
              ))}
            </div>

            <div className="grid grid-cols-7 gap-px bg-border">
              {Array.from({ length: firstWeekday }).map((_, i) => (
                <div key={`b-${i}`} className="min-h-[92px] bg-slate-50/40" />
              ))}
              {Array.from({ length: daysInMonth }).map((_, i) => {
                const day = i + 1
                const cellKey = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
                const isToday = cellKey === todayKey
                const dayEvts = sessionsByDay[cellKey] ?? []
                return (
                  <div key={day} className="min-h-[92px] bg-white p-1.5">
                    <div className="mb-1 flex justify-end pr-0.5">
                      <span
                        className={[
                          'flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-medium',
                          isToday ? 'text-white' : 'text-slate-500',
                        ].join(' ')}
                        style={
                          isToday
                            ? { background: paletteHex('primary', palette) ?? '#0f766e' }
                            : undefined
                        }
                      >{day}</span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      {dayEvts.map((g) => {
                        const s = sessionState(g, memberHasSeriesAccess)
                        const cs = stateChipStyles(s, palette)
                        return (
                          <Link
                            key={g.id}
                            href={`/spaces/${spaceSlug}/events/${g.id}`}
                            title={`${g.title} — ${stateLabel(s)}`}
                            className="block truncate rounded px-1.5 py-0.5 text-[10.5px] font-medium leading-tight transition-opacity hover:opacity-80"
                            style={{
                              background: cs.bg,
                              color: cs.color,
                              boxShadow: cs.ring ? `inset 0 0 0 1px ${cs.ring}` : undefined,
                            }}
                          >
                            <span className="opacity-75">{formatTimeShort(g.starts_at)}</span>{' '}
                            {g.title}
                          </Link>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Mobile: chronological list even when Calendar is
              toggled — a 7-col grid on a phone is unreadable. */}
          <div className="sm:hidden">
            <ScheduleList
              spaceSlug={spaceSlug}
              sessions={allSessions}
              memberHasSeriesAccess={memberHasSeriesAccess}
              palette={palette}
            />
          </div>
        </>
      )}

      {totalCount > 0 && view === 'list' && (
        <ScheduleList
          spaceSlug={spaceSlug}
          sessions={allSessions}
          memberHasSeriesAccess={memberHasSeriesAccess}
          palette={palette}
        />
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// List view — used on mobile always + desktop when List is chosen
// ---------------------------------------------------------------------------

function ScheduleList({
  spaceSlug, sessions, memberHasSeriesAccess, palette,
}: {
  spaceSlug: string
  sessions: SeriesScheduleGathering[]
  memberHasSeriesAccess: boolean
  palette: CollectivePaletteMeta | null
}) {
  const upcoming = sessions.filter((g) => !g.is_past)
  const past = sessions.filter((g) => g.is_past)
  return (
    <div className="space-y-2">
      {upcoming.map((g) => (
        <ListRow
          key={g.id}
          spaceSlug={spaceSlug}
          g={g}
          state={sessionState(g, memberHasSeriesAccess)}
          palette={palette}
        />
      ))}
      {past.length > 0 && (
        <details className="mt-6 rounded-xl border border-slate-200 bg-white">
          <summary className="cursor-pointer px-4 py-2.5 text-[12.5px] font-medium text-slate-600 hover:text-slate-800">
            Past Gatherings ({past.length})
          </summary>
          <ul className="divide-y divide-slate-100 border-t border-slate-100">
            {past.map((g) => (
              <li key={g.id}>
                <Link
                  href={`/spaces/${spaceSlug}/events/${g.id}`}
                  className="flex items-center justify-between gap-3 px-4 py-2.5 text-slate-500 hover:bg-slate-50"
                >
                  <div className="min-w-0">
                    <p className="truncate text-[13px]">{g.title}</p>
                    <p className="text-[11.5px]">{formatDateTime(g.starts_at)}</p>
                  </div>
                  <span className="text-[11px]">
                    {g.my_booking_status === 'confirmed' ? 'Attended' : 'Past'}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function ListRow({
  spaceSlug, g, state, palette,
}: {
  spaceSlug: string
  g: SeriesScheduleGathering
  state: SessionState
  palette: CollectivePaletteMeta | null
}) {
  const cs = stateChipStyles(state, palette)
  const format = g.attendance_format === 'in_person' ? 'In person' : 'Online'
  const locality = g.venue_locality ? ` · ${g.venue_locality}` : ''
  return (
    <Link
      href={`/spaces/${spaceSlug}/events/${g.id}`}
      className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-white px-4 py-3 transition-colors hover:border-[color:var(--fc-accent-line,rgba(56,160,158,0.24))]"
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px] font-medium text-navy-900">{g.title}</p>
        <p className="mt-0.5 text-[12px] text-slate-500">
          {formatDateTime(g.starts_at)} · {format}{locality}
          {g.capacity != null && g.spots_remaining != null && (
            <> · {g.booked_count}/{g.capacity} reserved</>
          )}
        </p>
      </div>
      <span
        className="shrink-0 rounded-full px-2.5 py-1 text-[11.5px] font-semibold"
        style={{
          background: cs.bg,
          color: cs.color,
          boxShadow: cs.ring ? `inset 0 0 0 1px ${cs.ring}` : undefined,
        }}
      >
        {stateLabel(state)}
      </span>
    </Link>
  )
}

// ---------------------------------------------------------------------------
// View toggle
// ---------------------------------------------------------------------------

function ViewToggleButton({
  active, onClick, label,
}: {
  active: boolean
  onClick: () => void
  label: string
}) {
  // Active state fills with the Collective palette primary so the
  // toggle feels branded on The Grove (warm rust) just as it does
  // on EMBODY (Ocean & Sand). Inactive state is neutral slate.
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className="rounded-full px-3 py-1 text-[12px] font-semibold transition-colors"
      style={active
        ? {
            background: 'var(--fc-accent, #0f172a)',
            color: 'var(--fc-accent-contrast, #FFFFFF)',
          }
        : { color: '#64748b' /* slate-500 */ }}
    >
      {label}
    </button>
  )
}
