'use client'

import { useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import { parseServerDatetime } from '@/lib/dateTime'
import { Button, Modal, useToast } from '@/components/platform'
import type {
  AttendanceDashboard,
  AttendanceRow,
  AttendanceStatus,
  AttendanceMutationResponse,
  AttendanceFinishResponse,
  AttendanceReopenResponse,
} from './types'

/**
 * Creator Studio attendance dashboard client component.
 *
 * Behaviour translated from the standalone prototype into Fresh
 * Collective's design system. The prototype's mechanics are preserved
 * (search, filter, check-in, undo, manual absence, finish preview,
 * reopen, summary, CSV export); prototype-only concerns (demo reset,
 * completed example loader, decorative garden SVG, custom sidebar,
 * local storage) are removed. Every mutation goes through the
 * same-origin BFF proxy at ``/api/creator/…`` and refreshes
 * ``counts`` from the authoritative server response.
 *
 * Fresh data: successful mutations return the whole counts block, so
 * the client never needs a follow-up GET to reconcile numbers.
 * Failed saves surface a toast; the pre-mutation row state is
 * preserved. 409 responses (gathering already finished / not
 * finished) trigger a full router.refresh() to re-hydrate from the
 * authoritative dashboard payload.
 */

type Filter = 'all' | 'booked' | 'attended' | 'absent'

interface Props {
  spaceSlug: string
  eventId: string
  initial: AttendanceDashboard
}

export default function AttendanceDashboardClient({
  spaceSlug, eventId, initial,
}: Props) {
  const router = useRouter()
  const toast = useToast()

  const [dashboard, setDashboard] = useState<AttendanceDashboard>(initial)
  const [tab, setTab] = useState<'attendees' | 'summary'>('attendees')
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const [busyBooking, setBusyBooking] = useState<string | null>(null)
  const [detailFor, setDetailFor] = useState<AttendanceRow | null>(null)
  const [showFinish, setShowFinish] = useState(false)
  const [showReopen, setShowReopen] = useState(false)
  const [finishing, setFinishing] = useState(false)
  const [reopening, setReopening] = useState(false)

  const { event, counts, bookings } = dashboard
  const isCompleted = event.attendance_completed_at !== null

  const filtered = useMemo(() => filterRows(bookings, filter, search), [bookings, filter, search])

  // --- API glue -----------------------------------------------------------

  async function apiJson<T>(url: string, init: RequestInit): Promise<T | { error: string; status: number }> {
    try {
      const res = await fetch(url, { credentials: 'include', ...init })
      if (res.status === 409) {
        // Completion state has shifted under us. Re-fetch authoritative data.
        router.refresh()
        return { error: 'shifted', status: 409 }
      }
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { const b = await res.json(); if (b?.detail) detail = String(b.detail) } catch {}
        return { error: detail, status: res.status }
      }
      return (await res.json()) as T
    } catch (e) {
      return { error: e instanceof Error ? e.message : 'network', status: 0 }
    }
  }

  function applyMutation(response: AttendanceMutationResponse) {
    setDashboard((prev) => ({
      ...prev,
      counts: response.counts,
      bookings: prev.bookings.map((b) => (
        b.booking_id === response.booking_id
          ? {
              ...b,
              attendance_status: response.attendance_status,
              attendance_source: response.attendance_source,
              attendance_marked_at: response.attendance_marked_at,
              pending_post_completion: false,
            }
          : b
      )),
    }))
  }

  async function setBookingStatus(row: AttendanceRow, next: AttendanceStatus) {
    if (busyBooking) return
    setBusyBooking(row.booking_id)
    const prev = row
    // Optimistic update — snappy check-in on desktop and mobile.
    setDashboard((d) => ({
      ...d,
      bookings: d.bookings.map((b) => (
        b.booking_id === row.booking_id
          ? { ...b, attendance_status: next, attendance_source: 'manual' }
          : b
      )),
    }))
    const res = await apiJson<AttendanceMutationResponse>(
      apiUrl(`/api/creator/spaces/${spaceSlug}/events/${eventId}/attendance/bookings/${row.booking_id}`),
      { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: next }) },
    )
    setBusyBooking(null)
    if ('error' in res) {
      // Roll back the optimistic update on any non-409 failure. 409 is
      // handled by router.refresh() above, which will replace the whole
      // payload with authoritative state.
      if (res.status !== 409) {
        setDashboard((d) => ({
          ...d,
          bookings: d.bookings.map((b) => (
            b.booking_id === row.booking_id ? prev : b
          )),
        }))
        toast.show(`Could not save. ${res.error}`, { tone: 'error' })
      }
      return
    }
    applyMutation(res)
    const name = row.name || row.email
    if (next === 'attended') {
      toast.show(`${name} checked in.`, { tone: 'success' })
    } else if (next === 'absent') {
      toast.show(`${name} marked absent.`)
    } else {
      toast.show(`${name} back to booked.`)
    }
  }

  async function confirmFinish() {
    setFinishing(true)
    const res = await apiJson<AttendanceFinishResponse>(
      apiUrl(`/api/creator/spaces/${spaceSlug}/events/${eventId}/attendance/finish`),
      { method: 'POST' },
    )
    setFinishing(false)
    setShowFinish(false)
    if ('error' in res) {
      if (res.status === 409) {
        toast.show('Attendance was already finished. Refreshing.')
      } else {
        toast.show(`Could not finish. ${res.error}`, { tone: 'error' })
      }
      return
    }
    setDashboard((d) => ({
      ...d,
      event: { ...d.event, attendance_completed_at: res.attendance_completed_at, attendance_completed_by: res.attendance_completed_by },
      counts: res.counts,
      bookings: d.bookings.map((b) => {
        if (b.attendance_status === 'booked') {
          return {
            ...b,
            attendance_status: 'absent',
            attendance_source: 'auto',
            attendance_marked_at: res.attendance_completed_at,
            in_finish_cohort: true,
          }
        }
        // Already attended / manual absent → stays as-is, now in cohort.
        if (b.attendance_status === 'attended' || b.attendance_status === 'absent') {
          return { ...b, in_finish_cohort: true }
        }
        return b
      }),
    }))
    setTab('summary')
    toast.show('Gathering complete. Attendance summary is ready.', { tone: 'success' })
  }

  async function confirmReopen() {
    setReopening(true)
    const res = await apiJson<AttendanceReopenResponse>(
      apiUrl(`/api/creator/spaces/${spaceSlug}/events/${eventId}/attendance/reopen`),
      { method: 'POST' },
    )
    setReopening(false)
    setShowReopen(false)
    if ('error' in res) {
      if (res.status === 409) {
        toast.show('Gathering is not currently finished. Refreshing.')
      } else {
        toast.show(`Could not reopen. ${res.error}`, { tone: 'error' })
      }
      return
    }
    setDashboard((d) => ({
      ...d,
      event: { ...d.event, attendance_completed_at: null, attendance_completed_by: null },
      counts: res.counts,
      // Under the in-progress rule cancelled rows disappear from the
      // roster (only confirmed rows remain). Drop cancelled-after-
      // completion entries so the client matches the server's next
      // GET without needing a router.refresh().
      bookings: d.bookings
        .filter((b) => !b.cancelled_after_completion)
        .map((b) => (
          b.attendance_status === 'absent' && b.attendance_source === 'auto'
            ? {
                ...b,
                attendance_status: 'booked',
                attendance_source: null,
                attendance_marked_at: null,
                in_finish_cohort: false,
              }
            : { ...b, in_finish_cohort: false }
        )),
    }))
    setTab('attendees')
    setFilter('all')
    setSearch('')
    toast.show('Check-in reopened. Manual entries are preserved.', { tone: 'success' })
  }

  // --- Render ------------------------------------------------------------

  return (
    <>
      <EventHeader event={event} />

      {counts.pending_post_completion > 0 && (
        <div
          role="status"
          className="mt-4 rounded-2xl border p-4 text-[13.5px]"
          style={{
            background: 'var(--fc-status-warning-bg, rgba(212,176,72,0.10))',
            borderColor: 'rgba(212,176,72,0.35)',
            color: '#6B5A16',
          }}
        >
          <strong>{counts.pending_post_completion} booking{counts.pending_post_completion === 1 ? '' : 's'}</strong>
          {' '}arrived after this gathering was finished. They&rsquo;re shown below but not counted in the summary. Reopen the gathering to include them.
        </div>
      )}

      <MetricsRow counts={counts} isCompleted={isCompleted} />

      <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
        <Tabs
          tab={tab} onChange={setTab}
          attendeesCount={counts.total_confirmed}
        />
        {isCompleted ? (
          <Button variant="secondary" size="md" onClick={() => setShowReopen(true)}>
            Reopen gathering
          </Button>
        ) : (
          <Button variant="primary" size="md" onClick={() => setShowFinish(true)}>
            Finish gathering
          </Button>
        )}
      </div>

      {tab === 'attendees' && (
        <AttendeesPanel
          rows={filtered}
          counts={counts}
          isCompleted={isCompleted}
          filter={filter}
          setFilter={setFilter}
          search={search}
          setSearch={setSearch}
          busyBooking={busyBooking}
          onCheckIn={(row) => setBookingStatus(row, 'attended')}
          onUndo={(row) => setBookingStatus(row, 'booked')}
          onDetails={(row) => setDetailFor(row)}
          exportHref={apiUrl(`/api/creator/spaces/${spaceSlug}/events/${eventId}/attendance/export.csv`)}
        />
      )}

      {tab === 'summary' && (
        <SummaryPanel
          counts={counts}
          rows={bookings}
          isCompleted={isCompleted}
          onOpenDetails={(row) => setDetailFor(row)}
          exportHref={apiUrl(`/api/creator/spaces/${spaceSlug}/events/${eventId}/attendance/export.csv`)}
          onBackToAttendees={() => setTab('attendees')}
        />
      )}

      {detailFor && (
        <BookingDetailModal
          row={detailFor}
          isCompleted={isCompleted}
          timezone={event.space_timezone}
          busy={busyBooking === detailFor.booking_id}
          onClose={() => setDetailFor(null)}
          onSave={async (next) => {
            const row = detailFor
            setDetailFor(null)
            if (row.attendance_status !== next) {
              await setBookingStatus(row, next)
            }
          }}
          onReopen={() => { setDetailFor(null); setShowReopen(true) }}
        />
      )}

      <Modal
        open={showFinish}
        onClose={() => setShowFinish(false)}
        title="Bring this gathering to a close?"
        size="md"
        actions={
          <>
            <Button variant="tertiary" size="md" onClick={() => setShowFinish(false)} disabled={finishing}>
              Keep checking in
            </Button>
            <Button variant="primary" size="md" onClick={confirmFinish} loading={finishing}>
              Finish &amp; view summary
            </Button>
          </>
        }
      >
        <p className="mb-4 text-[14px] leading-relaxed" style={{ color: 'var(--fc-ink-primary)' }}>
          {counts.booked === 0
            ? 'All bookings have an attendance status. Finishing creates the final attendance summary.'
            : `${counts.booked} ${counts.booked === 1 ? 'person is' : 'people are'} still booked. Finishing will mark them absent and create the attendance summary.`}
        </p>
        <div className="grid grid-cols-3 gap-3 rounded-xl border border-[color:var(--fc-border-hairline)] p-4">
          <PreviewNumber label="Attended" value={counts.attended} />
          <PreviewNumber label="Absent" value={counts.absent + counts.booked} />
          <PreviewNumber
            label="Attendance"
            value={counts.total_confirmed ? Math.round(100 * counts.attended / counts.total_confirmed) : 0}
            suffix="%"
          />
        </div>
        <p className="mt-4 text-[12.5px] italic" style={{ color: 'var(--fc-ink-tertiary, rgba(12,24,38,0.55))' }}>
          You can reopen the gathering at any time to make a correction.
        </p>
      </Modal>

      <Modal
        open={showReopen}
        onClose={() => setShowReopen(false)}
        title="Reopen check-in?"
        size="md"
        actions={
          <>
            <Button variant="tertiary" size="md" onClick={() => setShowReopen(false)} disabled={reopening}>
              Keep completed
            </Button>
            <Button variant="primary" size="md" onClick={confirmReopen} loading={reopening}>
              Reopen check-in
            </Button>
          </>
        }
      >
        <p className="text-[14px] leading-relaxed" style={{ color: 'var(--fc-ink-primary)' }}>
          Existing check-ins and people you manually marked absent will stay as they are. Everyone automatically marked absent when you finished will return to booked. Your summary will update as you make corrections.
        </p>
      </Modal>
    </>
  )
}


// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function EventHeader({ event }: { event: AttendanceDashboard['event'] }) {
  const artwork = resolveMediaUrl(event.thumbnail_url ?? undefined)
  const state = event.attendance_completed_at
    ? 'Completed'
    : (parseServerDatetime(event.starts_at).getTime() <= Date.now() ? 'Check-in open' : 'Upcoming')
  const stateColor = event.attendance_completed_at
    ? 'var(--fc-accent-700)'
    : 'var(--fc-status-neutral, #6B7280)'
  return (
    <section
      className="mt-4 overflow-hidden rounded-[var(--fc-radius-2xl)] border border-[color:var(--fc-border-hairline)] bg-white shadow-[var(--fc-elev-1)]"
    >
      <div className="grid gap-0 md:grid-cols-[minmax(0,1fr)_240px]">
        <div className="p-6 md:p-8">
          <div className="mb-2 flex flex-wrap items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'var(--fc-accent-700)' }}>
            <span>{event.space_name}</span>
            <span
              className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5"
              style={{ background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))', color: stateColor }}
            >
              <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: stateColor }} />
              {state}
            </span>
          </div>
          <h1 className="font-serif text-[26px] leading-tight md:text-[32px]" style={{ color: 'var(--fc-ink-primary)' }}>
            {event.title}
          </h1>
          {event.description && (
            <p className="mt-2 text-[14.5px] italic" style={{ color: 'var(--fc-ink-secondary, rgba(12,24,38,0.68))', fontFamily: 'Georgia, serif' }}>
              {event.description}
            </p>
          )}
          <dl className="mt-4 grid grid-cols-1 gap-2 text-[13px] md:grid-cols-2" style={{ color: 'var(--fc-ink-primary)' }}>
            <div>
              <dt className="text-[10.5px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'rgba(12,24,38,0.55)' }}>Date &amp; time</dt>
              <dd>{formatDateTime(event.starts_at, event.ends_at, event.space_timezone)}</dd>
            </div>
            <div>
              <dt className="text-[10.5px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'rgba(12,24,38,0.55)' }}>{event.attendance_format === 'online' ? 'Online' : 'Venue'}</dt>
              <dd>{formatVenue(event)}</dd>
            </div>
          </dl>
        </div>
        {artwork && (
          <div className="relative min-h-[160px] md:min-h-[220px]" style={{ background: 'linear-gradient(135deg, #E5F0EF 0%, #F4F7F6 60%, #FBFDFC 100%)' }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={artwork}
              alt=""
              className="h-full w-full"
              style={{ objectFit: 'cover', objectPosition: 'top', display: 'block' }}
            />
          </div>
        )}
      </div>
    </section>
  )
}


function formatDateTime(startIso: string, endIso: string | null, timezone: string): string {
  // ``parseServerDatetime`` appends a ``Z`` to the ISO string when it
  // lacks a timezone designator — the app-wide storage convention is
  // that a naive datetime represents UTC, but Chrome would otherwise
  // parse it as browser-local, showing wrong hours.
  const start = parseServerDatetime(startIso)
  const startFmt = new Intl.DateTimeFormat('en-AU', {
    timeZone: timezone,
    weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  }).format(start)
  if (!endIso) return startFmt
  const end = parseServerDatetime(endIso)
  // Same-day check in the collective's timezone, not the viewer's.
  const dayFmt = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' })
  const sameDay = dayFmt.format(start) === dayFmt.format(end)
  const endFmt = new Intl.DateTimeFormat('en-AU', sameDay
    ? { timeZone: timezone, hour: 'numeric', minute: '2-digit' }
    : { timeZone: timezone, weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' },
  ).format(end)
  return `${startFmt} – ${endFmt}`
}


function formatVenue(event: AttendanceDashboard['event']): string {
  if (event.attendance_format === 'online') {
    return event.location_url ? 'Online (link visible to attendees)' : 'Online'
  }
  const parts = [event.venue_name, event.venue_locality].filter(Boolean)
  return parts.length ? parts.join(' · ') : 'Venue to be confirmed'
}


// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

function MetricsRow({
  counts, isCompleted,
}: {
  counts: AttendanceDashboard['counts']
  isCompleted: boolean
}) {
  // Completed: the primary total is the cohort (finish-time set).
  // total_confirmed becomes a secondary "currently confirmed" label.
  // In progress: the primary total IS total_confirmed.
  const primaryTotal = isCompleted && counts.cohort_size != null ? counts.cohort_size : counts.total_confirmed
  const primaryLabel = isCompleted ? 'Bookings at finish' : 'Total bookings'
  const primaryCaption = isCompleted
    ? (counts.total_confirmed !== primaryTotal
        ? `Currently ${counts.total_confirmed} confirmed`
        : 'Bookings included in the completed record')
    : (counts.capacity ? `${Math.max(0, counts.capacity - counts.total_confirmed)} places available` : 'No capacity set')
  const primarySub = !isCompleted && counts.capacity ? `of ${counts.capacity}` : undefined
  return (
    <section className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4" aria-label="Attendance counts">
      <MetricCard
        label={primaryLabel}
        value={primaryTotal}
        sub={primarySub}
        caption={primaryCaption}
      />
      <MetricCard
        label="Attended"
        value={counts.attended}
        caption={isCompleted ? 'People who joined you' : 'Welcomed and checked in'}
        tone="success"
      />
      <MetricCard
        label={isCompleted ? 'Arrived after finish' : 'Awaiting check-in'}
        value={isCompleted ? counts.pending_post_completion : counts.booked}
        caption={isCompleted
          ? (counts.pending_post_completion === 0 ? 'None — cohort intact' : 'Not in the completed record')
          : 'Booked, not checked in yet'}
      />
      <MetricCard
        label="Absent"
        value={counts.absent}
        caption={isCompleted ? 'Didn’t join this time' : 'Marked as not attending'}
        tone="muted"
      />
    </section>
  )
}


function MetricCard({
  label, value, sub, caption, tone,
}: {
  label: string
  value: number
  sub?: string
  caption?: string
  tone?: 'success' | 'muted'
}) {
  const accent = tone === 'success' ? 'var(--fc-accent-700)'
    : tone === 'muted' ? 'var(--fc-ink-secondary, rgba(12,24,38,0.55))'
    : 'var(--fc-ink-primary)'
  return (
    <div
      className="rounded-[var(--fc-radius-lg)] border border-[color:var(--fc-border-hairline)] bg-white p-4"
    >
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'rgba(12,24,38,0.55)' }}>
        {label}
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="font-serif text-[28px] leading-none" style={{ color: accent }}>
          {value}
        </span>
        {sub && <span className="text-[13px]" style={{ color: 'rgba(12,24,38,0.55)' }}>{sub}</span>}
      </div>
      {caption && (
        <p className="mt-1.5 text-[12px]" style={{ color: 'rgba(12,24,38,0.60)' }}>
          {caption}
        </p>
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

function Tabs({
  tab, onChange, attendeesCount,
}: {
  tab: 'attendees' | 'summary'
  onChange: (v: 'attendees' | 'summary') => void
  attendeesCount: number
}) {
  const base = 'inline-flex items-center gap-2 rounded-full px-4 py-2 text-[13px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--fc-accent-500)]/40'
  return (
    <div className="flex flex-wrap items-center gap-2" role="tablist">
      <button
        type="button"
        role="tab"
        aria-selected={tab === 'attendees'}
        onClick={() => onChange('attendees')}
        className={base}
        style={{
          background: tab === 'attendees' ? 'var(--fc-accent-soft, rgba(56,160,158,0.12))' : 'transparent',
          color: tab === 'attendees' ? 'var(--fc-accent-700)' : 'rgba(12,24,38,0.62)',
        }}
      >
        Attendees
        <span
          className="rounded-full px-1.5 py-0.5 text-[11px] font-semibold"
          style={{ background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.75)' }}
        >
          {attendeesCount}
        </span>
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={tab === 'summary'}
        onClick={() => onChange('summary')}
        className={base}
        style={{
          background: tab === 'summary' ? 'var(--fc-accent-soft, rgba(56,160,158,0.12))' : 'transparent',
          color: tab === 'summary' ? 'var(--fc-accent-700)' : 'rgba(12,24,38,0.62)',
        }}
      >
        Attendance summary
      </button>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Attendees panel
// ---------------------------------------------------------------------------

function AttendeesPanel({
  rows, counts, isCompleted, filter, setFilter, search, setSearch,
  busyBooking, onCheckIn, onUndo, onDetails, exportHref,
}: {
  rows: AttendanceRow[]
  counts: AttendanceDashboard['counts']
  isCompleted: boolean
  filter: Filter
  setFilter: (f: Filter) => void
  search: string
  setSearch: (s: string) => void
  busyBooking: string | null
  onCheckIn: (row: AttendanceRow) => void
  onUndo: (row: AttendanceRow) => void
  onDetails: (row: AttendanceRow) => void
  exportHref: string
}) {
  return (
    <section className="mt-6 rounded-[var(--fc-radius-2xl)] border border-[color:var(--fc-border-hairline)] bg-white p-5 md:p-7">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-serif text-[19px]" style={{ color: 'var(--fc-ink-primary)' }}>
            A place for everyone
          </h2>
          <p className="mt-0.5 text-[13px]" style={{ color: 'rgba(12,24,38,0.60)' }}>
            {isCompleted ? 'The final attendance record for this gathering.' : 'Find a name, say hello, check them in.'}
          </p>
        </div>
        <a
          href={exportHref}
          className="inline-flex h-10 items-center gap-2 rounded-[var(--fc-radius-md)] border border-[color:var(--fc-border-input)] px-4 text-[13px] font-semibold text-[color:var(--fc-ink-primary)] transition-opacity hover:opacity-90"
        >
          Export CSV
        </a>
      </div>

      <div className="mb-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
        <label className="relative block">
          <span className="sr-only">Search attendees</span>
          <input
            type="search"
            placeholder="Search name, email or booking reference…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-10 w-full rounded-[var(--fc-radius-md)] border border-[color:var(--fc-border-input)] bg-white px-3 text-[14px] focus:outline-none focus:ring-2 focus:ring-[color:var(--fc-accent-500)]/40"
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <FilterButton active={filter === 'all'} onClick={() => setFilter('all')} label="All" count={counts.total_confirmed} />
          <FilterButton active={filter === 'booked'} onClick={() => setFilter('booked')} label="Booked" count={counts.booked} />
          <FilterButton active={filter === 'attended'} onClick={() => setFilter('attended')} label="Attended" count={counts.attended} />
          <FilterButton active={filter === 'absent'} onClick={() => setFilter('absent')} label="Absent" count={counts.absent} />
        </div>
      </div>

      <div className="overflow-hidden rounded-[var(--fc-radius-lg)] border border-[color:var(--fc-border-hairline)]">
        <table className="w-full border-collapse text-left text-[13.5px]">
          <thead>
            <tr style={{ background: 'var(--fc-surface-muted, rgba(12,24,38,0.03))' }}>
              <th className="px-4 py-3 font-semibold" style={{ color: 'rgba(12,24,38,0.65)' }}>Attendee</th>
              <th className="hidden px-4 py-3 font-semibold md:table-cell" style={{ color: 'rgba(12,24,38,0.65)' }}>Booking</th>
              <th className="px-4 py-3 font-semibold" style={{ color: 'rgba(12,24,38,0.65)' }}>Status</th>
              <th className="px-4 py-3 text-right font-semibold" style={{ color: 'rgba(12,24,38,0.65)' }}>Check-in</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-6 py-8 text-center text-[13.5px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
                  {search || filter !== 'all'
                    ? 'No attendees match this filter. Try clearing the search.'
                    : 'No confirmed bookings yet.'}
                </td>
              </tr>
            ) : rows.map((r) => (
              <AttendeeRow
                key={r.booking_id}
                row={r}
                isCompleted={isCompleted}
                busy={busyBooking === r.booking_id}
                onCheckIn={onCheckIn}
                onUndo={onUndo}
                onDetails={onDetails}
              />
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-[12px] italic" style={{ color: 'rgba(12,24,38,0.55)' }}>
        {isCompleted
          ? 'Attendance is complete. Reopen the gathering to make a correction.'
          : 'Booked means expected. When you finish the gathering, anyone still booked will be marked absent. You can make corrections afterwards.'}
      </p>
    </section>
  )
}


function FilterButton({
  active, onClick, label, count,
}: { active: boolean; onClick: () => void; label: string; count: number }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className="inline-flex h-9 items-center gap-1.5 rounded-full border px-3 text-[12.5px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--fc-accent-500)]/40"
      style={{
        background: active ? 'var(--fc-accent-soft, rgba(56,160,158,0.12))' : 'transparent',
        borderColor: active ? 'transparent' : 'var(--fc-border-hairline)',
        color: active ? 'var(--fc-accent-700)' : 'rgba(12,24,38,0.75)',
      }}
    >
      {label}
      <span
        className="rounded-full px-1.5 text-[11px]"
        style={{ background: active ? 'rgba(56,160,158,0.16)' : 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.75)' }}
      >
        {count}
      </span>
    </button>
  )
}


function AttendeeRow({
  row, isCompleted, busy, onCheckIn, onUndo, onDetails,
}: {
  row: AttendanceRow
  isCompleted: boolean
  busy: boolean
  onCheckIn: (row: AttendanceRow) => void
  onUndo: (row: AttendanceRow) => void
  onDetails: (row: AttendanceRow) => void
}) {
  return (
    <tr className="border-t border-[color:var(--fc-border-hairline)]">
      <td className="px-4 py-3 align-top">
        <div className="flex items-center gap-3">
          <span
            className="grid h-9 w-9 place-items-center rounded-full text-[12px] font-semibold"
            style={{ background: 'rgba(56,160,158,0.10)', color: 'var(--fc-accent-700)' }}
            aria-hidden="true"
          >
            {initials(row.name || row.email)}
          </span>
          <div>
            <button
              type="button"
              onClick={() => onDetails(row)}
              className="text-[14px] font-semibold underline-offset-2 hover:underline"
              style={{ color: 'var(--fc-ink-primary)' }}
            >
              {row.name || row.email}
            </button>
            <div className="text-[12px]" style={{ color: 'rgba(12,24,38,0.60)' }}>
              {row.email}
            </div>
            {row.pending_post_completion && (
              <span className="mt-1 mr-1 inline-block rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.14em]"
                style={{ background: 'rgba(212,176,72,0.14)', color: '#6B5A16' }}>
                Booked after finish
              </span>
            )}
            {row.cancelled_after_completion && (
              <span className="mt-1 inline-block rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.14em]"
                style={{ background: 'rgba(154,62,62,0.10)', color: '#7A2E2E' }}
                title="This booking was cancelled after the gathering was finished. The attendance value is frozen at the time of finish."
              >
                Cancelled after finish
              </span>
            )}
          </div>
        </div>
      </td>
      <td className="hidden px-4 py-3 align-top md:table-cell">
        <div className="text-[13px]" style={{ color: 'var(--fc-ink-primary)' }}>{row.ticket_label}</div>
        <div className="text-[12px]" style={{ color: 'rgba(12,24,38,0.60)' }}>{row.payment_label} · {row.booking_reference}</div>
      </td>
      <td className="px-4 py-3 align-top">
        <StatusPill status={row.attendance_status} source={row.attendance_source} />
      </td>
      <td className="px-4 py-3 align-top text-right">
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          {isCompleted ? (
            <button
              type="button"
              onClick={() => onDetails(row)}
              className="inline-flex h-8 items-center rounded-[var(--fc-radius-md)] border border-[color:var(--fc-border-input)] px-3 text-[12px] font-semibold"
              style={{ color: 'var(--fc-ink-primary)' }}
            >
              View
            </button>
          ) : row.attendance_status === 'attended' ? (
            <button
              type="button"
              onClick={() => onUndo(row)}
              disabled={busy}
              className="inline-flex h-8 items-center rounded-[var(--fc-radius-md)] px-3 text-[12px] font-semibold disabled:opacity-40"
              style={{ background: 'var(--fc-accent-soft, rgba(56,160,158,0.14))', color: 'var(--fc-accent-700)' }}
            >
              Undo
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onCheckIn(row)}
              disabled={busy}
              className="inline-flex h-8 items-center gap-1 rounded-[var(--fc-radius-md)] px-3 text-[12px] font-semibold text-white transition-opacity disabled:opacity-40"
              style={{ background: 'var(--fc-accent-gradient, linear-gradient(135deg,#38A09E 0%,#55B8B6 100%))' }}
            >
              ✓ Check in
            </button>
          )}
          {!isCompleted && (
            <button
              type="button"
              onClick={() => onDetails(row)}
              aria-label={`Booking details for ${row.name || row.email}`}
              className="grid h-8 w-8 place-items-center rounded-[var(--fc-radius-md)] border border-[color:var(--fc-border-input)]"
              style={{ color: 'rgba(12,24,38,0.60)' }}
            >
              ⋯
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}


function StatusPill({ status, source }: { status: AttendanceStatus; source: AttendanceRow['attendance_source'] }) {
  const config: Record<AttendanceStatus, { bg: string; fg: string; label: string }> = {
    attended: { bg: 'rgba(56,160,158,0.14)', fg: 'var(--fc-accent-700)', label: 'Attended' },
    absent:   { bg: 'rgba(190,120,120,0.14)', fg: '#9A3E3E', label: 'Absent' },
    booked:   { bg: 'rgba(12,24,38,0.06)', fg: 'rgba(12,24,38,0.72)', label: 'Booked' },
  }
  const c = config[status]
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold" style={{ background: c.bg, color: c.fg }}>
      {c.label}
      {status === 'absent' && source === 'auto' && (
        <span className="ml-1 rounded-full px-1.5 text-[10px] font-normal" style={{ background: 'rgba(0,0,0,0.05)' }}>auto</span>
      )}
    </span>
  )
}


function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((n) => n[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase()
}


// ---------------------------------------------------------------------------
// Summary panel
// ---------------------------------------------------------------------------

function SummaryPanel({
  counts, rows, isCompleted, onOpenDetails, exportHref, onBackToAttendees,
}: {
  counts: AttendanceDashboard['counts']
  rows: AttendanceRow[]
  isCompleted: boolean
  onOpenDetails: (row: AttendanceRow) => void
  exportHref: string
  onBackToAttendees: () => void
}) {
  // Rate denominator: cohort_size when completed, live confirmed
  // while in progress. Both derived from server-returned counts —
  // never from browser-held Finish-response values.
  const denominator = isCompleted && counts.cohort_size != null
    ? counts.cohort_size
    : counts.total_confirmed
  const rate = denominator ? Math.round(100 * counts.attended / denominator) : 0
  // Absent list on the completed summary excludes cancelled-after-finish
  // rows only if the creator wants a clean "who missed" list; the pill
  // in the roster already labels them. Keep them here — they are part
  // of the cohort and part of the absent number.
  const absent = rows.filter((r) => r.attendance_status === 'absent')
  // Ticket breakdown: only count cohort members when completed, so
  // the "N of M attended" matches the cohort-based numerators. Live
  // mode uses currently-confirmed rows (attendance_status set counts
  // as attended; anything else counts toward total).
  const ticketGroups = new Map<string, { total: number; attended: number }>()
  for (const r of rows) {
    if (isCompleted && !r.in_finish_cohort) continue
    const g = ticketGroups.get(r.ticket_label) ?? { total: 0, attended: 0 }
    g.total += 1
    if (r.attendance_status === 'attended') g.attended += 1
    ticketGroups.set(r.ticket_label, g)
  }

  return (
    <section className="mt-6 grid gap-5 md:grid-cols-2">
      {!isCompleted && (
        <div className="md:col-span-2 rounded-[var(--fc-radius-2xl)] border border-[color:var(--fc-border-hairline)] bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="font-serif text-[16px]" style={{ color: 'var(--fc-ink-primary)' }}>Your summary is taking shape.</p>
              <p className="text-[12.5px]" style={{ color: 'rgba(12,24,38,0.60)' }}>
                These numbers update as you check people in. Finish the gathering to finalise attendance.
              </p>
            </div>
            <Button variant="tertiary" size="md" onClick={onBackToAttendees}>Back to check-in →</Button>
          </div>
        </div>
      )}

      <div className="rounded-[var(--fc-radius-2xl)] border border-[color:var(--fc-border-hairline)] bg-white p-6">
        <p className="text-[10.5px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'var(--fc-accent-700)' }}>
          {isCompleted ? 'Gathering complete' : 'Live attendance'}
        </p>
        <h3 className="mt-1 font-serif text-[22px]" style={{ color: 'var(--fc-ink-primary)' }}>
          {isCompleted ? 'A moment shared.' : 'Every arrival matters.'}
        </h3>
        <div className="mt-5 flex items-center gap-6">
          <AttendanceRing rate={rate} />
          <div className="grid gap-2 text-[13px]">
            <LegendItem label="Attended" value={counts.attended} color="var(--fc-accent-700)" />
            <LegendItem label="Absent" value={counts.absent} color="#9A3E3E" />
            <LegendItem label="Still booked" value={counts.booked} color="rgba(12,24,38,0.55)" />
          </div>
        </div>
      </div>

      <div className="rounded-[var(--fc-radius-2xl)] border border-[color:var(--fc-border-hairline)] bg-white p-6">
        <h3 className="font-serif text-[19px]" style={{ color: 'var(--fc-ink-primary)' }}>The details, together.</h3>
        <p className="mt-1 text-[12.5px]" style={{ color: 'rgba(12,24,38,0.60)' }}>Attendance by booking type</p>
        <div className="mt-3 grid gap-2.5">
          {[...ticketGroups.entries()].map(([label, g]) => (
            <div key={label} className="text-[13px]">
              <div className="mb-1 flex items-baseline justify-between">
                <span style={{ color: 'var(--fc-ink-primary)' }}>{label}</span>
                <strong style={{ color: 'var(--fc-ink-primary)' }}>{g.attended} of {g.total} attended</strong>
              </div>
              <div className="h-1.5 rounded-full" style={{ background: 'rgba(12,24,38,0.06)' }}>
                <div
                  className="h-full rounded-full"
                  style={{ width: `${g.total ? Math.round(100 * g.attended / g.total) : 0}%`, background: 'var(--fc-accent-gradient, linear-gradient(90deg,#38A09E,#55B8B6))' }}
                />
              </div>
            </div>
          ))}
        </div>
        <div className="mt-6">
          <h4 className="text-[10.5px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'rgba(12,24,38,0.55)' }}>
            {isCompleted ? 'Couldn’t join this time' : 'Marked absent'} <span className="ml-1 text-[12px]">{counts.absent}</span>
          </h4>
          {absent.length ? (
            <ul className="mt-2 grid gap-1.5">
              {absent.map((r) => (
                <li key={r.booking_id} className="flex items-center justify-between text-[13px]">
                  <span style={{ color: 'var(--fc-ink-primary)' }}>{r.name || r.email}</span>
                  <button
                    type="button"
                    onClick={() => onOpenDetails(r)}
                    className="text-[12px] font-semibold"
                    style={{ color: 'var(--fc-accent-700)' }}
                  >
                    View booking
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-[13px] italic" style={{ color: 'rgba(12,24,38,0.55)' }}>
              {isCompleted ? 'Everyone made it — a full room.' : 'No one has been marked absent yet.'}
            </p>
          )}
        </div>
      </div>

      <div className="md:col-span-2 flex justify-end">
        <a
          href={exportHref}
          className="inline-flex h-10 items-center gap-2 rounded-[var(--fc-radius-md)] border border-[color:var(--fc-border-input)] px-4 text-[13px] font-semibold text-[color:var(--fc-ink-primary)] transition-opacity hover:opacity-90"
        >
          Export attendance report
        </a>
      </div>

      <p className="md:col-span-2 text-[11.5px] italic" style={{ color: 'rgba(12,24,38,0.55)' }}>
        Attendance rate = attended ÷ total confirmed bookings. Cancelled bookings are excluded from the denominator.
      </p>
    </section>
  )
}


function AttendanceRing({ rate }: { rate: number }) {
  const r = 40
  const c = 2 * Math.PI * r
  const offset = c * (1 - rate / 100)
  return (
    <svg width={110} height={110} viewBox="0 0 110 110" role="img" aria-label={`${rate}% attendance`}>
      <circle cx={55} cy={55} r={r} fill="none" stroke="rgba(12,24,38,0.08)" strokeWidth={10} />
      <circle
        cx={55} cy={55} r={r} fill="none"
        stroke="url(#ring-grad)"
        strokeWidth={10}
        strokeDasharray={c}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform="rotate(-90 55 55)"
      />
      <defs>
        <linearGradient id="ring-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#38A09E" />
          <stop offset="100%" stopColor="#55B8B6" />
        </linearGradient>
      </defs>
      <text x="55" y="60" textAnchor="middle" fontFamily="Georgia, serif" fontSize="22" fill="#0C1826">{rate}%</text>
    </svg>
  )
}


function LegendItem({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />
      <span style={{ color: 'rgba(12,24,38,0.65)' }}>{label}</span>
      <strong style={{ color: 'var(--fc-ink-primary)' }}>{value}</strong>
    </div>
  )
}


function PreviewNumber({ label, value, suffix }: { label: string; value: number; suffix?: string }) {
  return (
    <div>
      <div className="font-serif text-[24px] leading-none" style={{ color: 'var(--fc-ink-primary)' }}>
        {value}{suffix}
      </div>
      <div className="mt-1 text-[11px]" style={{ color: 'rgba(12,24,38,0.60)' }}>{label}</div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Detail modal
// ---------------------------------------------------------------------------

function BookingDetailModal({
  row, isCompleted, timezone, busy, onClose, onSave, onReopen,
}: {
  row: AttendanceRow
  isCompleted: boolean
  timezone: string
  busy: boolean
  onClose: () => void
  onSave: (next: AttendanceStatus) => void
  onReopen: () => void
}) {
  const [selected, setSelected] = useState<AttendanceStatus>(row.attendance_status)
  return (
    <Modal
      open={true}
      onClose={onClose}
      title={row.name || row.email}
      size="md"
      actions={
        isCompleted ? (
          <>
            <Button variant="tertiary" size="md" onClick={onClose}>Close</Button>
            <Button variant="primary" size="md" onClick={onReopen}>Reopen gathering</Button>
          </>
        ) : (
          <>
            <Button variant="tertiary" size="md" onClick={onClose} disabled={busy}>Cancel</Button>
            <Button variant="primary" size="md" onClick={() => onSave(selected)} loading={busy}>Save attendance</Button>
          </>
        )
      }
    >
      <p className="mb-4 text-[13px]" style={{ color: 'rgba(12,24,38,0.60)' }}>{row.email}</p>

      <dl className="mb-5 grid gap-2 text-[13.5px]" style={{ color: 'var(--fc-ink-primary)' }}>
        <div className="grid grid-cols-[110px_1fr] gap-3">
          <dt className="text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'rgba(12,24,38,0.55)' }}>Reference</dt>
          <dd>{row.booking_reference}</dd>
        </div>
        <div className="grid grid-cols-[110px_1fr] gap-3">
          <dt className="text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'rgba(12,24,38,0.55)' }}>Ticket</dt>
          <dd>{row.ticket_label}</dd>
        </div>
        <div className="grid grid-cols-[110px_1fr] gap-3">
          <dt className="text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'rgba(12,24,38,0.55)' }}>Payment</dt>
          <dd>{row.payment_label}</dd>
        </div>
        <div className="grid grid-cols-[110px_1fr] gap-3">
          <dt className="text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'rgba(12,24,38,0.55)' }}>Booked on</dt>
          <dd>{parseServerDatetime(row.booked_at).toLocaleString('en-AU', { timeZone: timezone, day: 'numeric', month: 'short', year: 'numeric' })}</dd>
        </div>
        <div className="grid grid-cols-[110px_1fr] gap-3">
          <dt className="text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'rgba(12,24,38,0.55)' }}>Attendance</dt>
          <dd><StatusPill status={row.attendance_status} source={row.attendance_source} /></dd>
        </div>
        {row.attendance_marked_at && (
          <div className="grid grid-cols-[110px_1fr] gap-3">
            <dt className="text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'rgba(12,24,38,0.55)' }}>Checked in</dt>
            <dd>{parseServerDatetime(row.attendance_marked_at).toLocaleString('en-AU', { timeZone: timezone, day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })}</dd>
          </div>
        )}
      </dl>

      {row.booking_note && (
        <div className="mb-5 rounded-[var(--fc-radius-md)] border border-[color:var(--fc-border-hairline)] p-3 text-[13px]" style={{ background: 'var(--fc-surface-muted, rgba(12,24,38,0.03))' }}>
          <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'rgba(12,24,38,0.55)' }}>Booking note</div>
          <p style={{ color: 'var(--fc-ink-primary)', fontFamily: 'Georgia, serif' }}>{row.booking_note}</p>
        </div>
      )}

      {!isCompleted && (
        <fieldset>
          <legend className="mb-2 text-[11.5px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'rgba(12,24,38,0.55)' }}>
            Update attendance
          </legend>
          <div className="flex flex-wrap gap-2">
            {(['booked', 'attended', 'absent'] as AttendanceStatus[]).map((s) => (
              <label key={s} className="inline-flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-[13px] font-semibold"
                style={{
                  background: selected === s ? 'var(--fc-accent-soft, rgba(56,160,158,0.12))' : 'transparent',
                  borderColor: selected === s ? 'transparent' : 'var(--fc-border-hairline)',
                  color: selected === s ? 'var(--fc-accent-700)' : 'rgba(12,24,38,0.72)',
                }}
              >
                <input
                  type="radio"
                  name="status"
                  value={s}
                  checked={selected === s}
                  onChange={() => setSelected(s)}
                  className="sr-only"
                />
                {s === 'booked' ? 'Booked' : s === 'attended' ? 'Attended' : 'Absent'}
              </label>
            ))}
          </div>
          <p className="mt-2 text-[11.5px] italic" style={{ color: 'rgba(12,24,38,0.55)' }}>
            Use absent if you already know they won&rsquo;t be joining.
          </p>
        </fieldset>
      )}
    </Modal>
  )
}


// ---------------------------------------------------------------------------
// Filtering helper
// ---------------------------------------------------------------------------


function filterRows(rows: AttendanceRow[], filter: Filter, search: string): AttendanceRow[] {
  const q = search.trim().toLowerCase()
  return rows.filter((r) => {
    if (filter !== 'all' && r.attendance_status !== filter) return false
    if (!q) return true
    return (
      (r.name ?? '').toLowerCase().includes(q)
      || r.email.toLowerCase().includes(q)
      || r.booking_reference.toLowerCase().includes(q)
      || r.ticket_label.toLowerCase().includes(q)
    )
  })
}
