'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type { CreatorEvent, EventBooking } from '@/types/platform'

interface SpaceMember {
  id: string
  display_name: string
}

interface Props {
  event: CreatorEvent
  spaceSlug: string
  initialBookings: EventBooking[]
  members: SpaceMember[]
}

const ATTENDANCE_STYLES: Record<string, { label: string; bg: string; color: string }> = {
  attended: { label: 'Attended',  bg: 'rgba(56,160,158,0.12)',  color: '#0f766e' },
  no_show:  { label: 'No show',   bg: 'rgba(239,68,68,0.08)',   color: '#b91c1c' },
  pending:  { label: 'Pending',   bg: 'rgba(148,163,184,0.12)', color: '#64748b' },
}

function AttendancePill({ status }: { status: string | null }) {
  const s = status ? (ATTENDANCE_STYLES[status] ?? ATTENDANCE_STYLES.pending) : ATTENDANCE_STYLES.pending
  return (
    <span className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold" style={{ background: s.bg, color: s.color }}>
      {s.label}
    </span>
  )
}

function AttendanceButtons({ bookingId, eventId, spaceSlug, currentStatus, onUpdated }: {
  bookingId: string
  eventId: string
  spaceSlug: string
  currentStatus: string | null
  onUpdated: (bookingId: string, status: string | null) => void
}) {
  const [busy, setBusy] = useState(false)

  async function mark(status: string) {
    setBusy(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/events/${eventId}/bookings/${bookingId}/attendance`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status }),
        },
      )
      if (res.ok) {
        const data = await res.json()
        onUpdated(bookingId, data.attendance_status)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {currentStatus !== 'attended' && (
        <button onClick={() => mark('attended')} disabled={busy}
          className="rounded-md px-2 py-0.5 text-[10px] font-semibold transition-colors disabled:opacity-40"
          style={{ background: 'rgba(56,160,158,0.10)', color: '#0f766e' }}>
          ✓ Attended
        </button>
      )}
      {currentStatus !== 'no_show' && (
        <button onClick={() => mark('no_show')} disabled={busy}
          className="rounded-md px-2 py-0.5 text-[10px] font-semibold transition-colors disabled:opacity-40"
          style={{ background: 'rgba(239,68,68,0.06)', color: '#b91c1c' }}>
          ✗ No show
        </button>
      )}
      {currentStatus && currentStatus !== 'pending' && (
        <button onClick={() => mark('pending')} disabled={busy}
          className="rounded-md px-2 py-0.5 text-[10px] font-medium text-slate-400 transition-colors hover:text-slate-600 disabled:opacity-40">
          Reset
        </button>
      )}
    </div>
  )
}

export default function EventManagePanel({ event, spaceSlug, initialBookings, members }: Props) {
  const router = useRouter()
  const isCancelled = event.status === 'cancelled'
  const isPast = new Date(event.starts_at) < new Date()

  // Cancel event
  const [showCancelConfirm, setShowCancelConfirm] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [cancelError, setCancelError] = useState<string | null>(null)

  // Bookings
  const [bookings, setBookings] = useState<EventBooking[]>(initialBookings)

  // Manual booking
  const [showAddBooking, setShowAddBooking] = useState(false)
  const [selectedUserId, setSelectedUserId] = useState('')
  const [bookingNote, setBookingNote] = useState('')
  const [addingBooking, setAddingBooking] = useState(false)
  const [addBookingError, setAddBookingError] = useState<string | null>(null)

  // Cancel booking
  const [cancellingBookingId, setCancellingBookingId] = useState<string | null>(null)

  async function handleCancelEvent() {
    setCancelling(true)
    setCancelError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/events/${event.id}/cancel`), {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { const b = await res.json(); detail = typeof b.detail === 'string' ? b.detail : detail } catch {}
        throw new Error(detail)
      }
      router.push(`/creator/spaces/${spaceSlug}/events`)
      router.refresh()
    } catch (err) {
      setCancelError(err instanceof Error ? err.message : 'Could not cancel session.')
      setCancelling(false)
    }
  }

  async function handleAddBooking() {
    if (!selectedUserId) return
    setAddingBooking(true)
    setAddBookingError(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/events/${event.id}/bookings/manual`), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: selectedUserId, note: bookingNote || null }),
      })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { const b = await res.json(); detail = typeof b.detail === 'string' ? b.detail : detail } catch {}
        throw new Error(detail)
      }
      const listRes = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/events/${event.id}/bookings`), {
        credentials: 'include',
      })
      if (listRes.ok) setBookings(await listRes.json())
      setShowAddBooking(false)
      setSelectedUserId('')
      setBookingNote('')
    } catch (err) {
      setAddBookingError(err instanceof Error ? err.message : 'Could not add booking.')
    } finally {
      setAddingBooking(false)
    }
  }

  async function handleCancelBooking(bookingId: string) {
    setCancellingBookingId(bookingId)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/events/${event.id}/bookings/${bookingId}/cancel`), {
        method: 'POST',
        credentials: 'include',
      })
      if (res.ok) {
        setBookings(prev => prev.map(b => b.booking_id === bookingId ? { ...b, status: 'cancelled' as const } : b))
      }
    } finally {
      setCancellingBookingId(null)
    }
  }

  function handleAttendanceUpdated(bookingId: string, status: string | null) {
    setBookings(prev => prev.map(b =>
      b.booking_id === bookingId
        ? { ...b, attendance_status: status as EventBooking['attendance_status'] }
        : b
    ))
  }

  const confirmedBookings = bookings.filter(b => b.status === 'confirmed')
  const cancelledBookings = bookings.filter(b => b.status === 'cancelled')

  // Attendance summary for past sessions
  const attendedCount  = confirmedBookings.filter(b => b.attendance_status === 'attended').length
  const noShowCount    = confirmedBookings.filter(b => b.attendance_status === 'no_show').length
  const pendingCount   = confirmedBookings.filter(b => !b.attendance_status || b.attendance_status === 'pending').length

  // Members not already confirmed
  const availableMembers = members.filter(
    m => !confirmedBookings.some(b => b.user_id === m.id)
  )

  return (
    <div className="mt-10 flex flex-col gap-8">

      {/* ── Booked members ── */}
      {event.requires_booking && (
        <div>
          <div className="mb-4 h-px w-6 bg-gold-400" />
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="font-serif text-xl text-navy-900">
                Bookings
                {event.capacity != null && (
                  <span className="ml-2 text-sm font-normal text-slate-400">
                    {confirmedBookings.length} / {event.capacity}
                  </span>
                )}
                {event.capacity == null && confirmedBookings.length > 0 && (
                  <span className="ml-2 text-sm font-normal text-slate-400">
                    {confirmedBookings.length} booked
                  </span>
                )}
              </h2>
              {/* Attendance summary for past sessions */}
              {isPast && !isCancelled && confirmedBookings.length > 0 && (
                <p className="mt-1 text-[12px] text-slate-400">
                  {attendedCount > 0 && <span className="mr-3 text-teal-600">{attendedCount} attended</span>}
                  {noShowCount > 0 && <span className="mr-3 text-red-500">{noShowCount} no show</span>}
                  {pendingCount > 0 && <span>{pendingCount} not marked</span>}
                </p>
              )}
              {!isPast && !isCancelled && (
                <p className="mt-1 text-[12px] text-slate-400">
                  Attendance can be marked once this session has started.
                </p>
              )}
            </div>
            {!isCancelled && (
              <button
                onClick={() => setShowAddBooking(v => !v)}
                className="rounded-lg bg-navy-900 px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
              >
                {showAddBooking ? 'Cancel' : '+ Add booking'}
              </button>
            )}
          </div>

          {/* Manual booking form */}
          {showAddBooking && (
            <div className="mb-5 rounded-xl border border-border bg-slate-50/50 p-5">
              <p className="mb-3 text-sm font-semibold text-navy-800">Add a booking</p>
              <div className="flex flex-col gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-500">Member</label>
                  <select
                    value={selectedUserId}
                    onChange={e => setSelectedUserId(e.target.value)}
                    className="w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm text-navy-900 focus:outline-none focus:ring-1 focus:ring-navy-300"
                  >
                    <option value="">Select a member…</option>
                    {availableMembers.map(m => (
                      <option key={m.id} value={m.id}>{m.display_name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-500">Note (optional)</label>
                  <input
                    value={bookingNote}
                    onChange={e => setBookingNote(e.target.value)}
                    placeholder="Internal note about this booking"
                    className="w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm text-navy-900 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-navy-300"
                  />
                </div>
                {addBookingError && <p className="text-xs text-red-500">{addBookingError}</p>}
                <button
                  onClick={handleAddBooking}
                  disabled={!selectedUserId || addingBooking}
                  className="self-start rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {addingBooking ? 'Adding…' : 'Confirm booking'}
                </button>
              </div>
            </div>
          )}

          {/* Confirmed bookings list */}
          {confirmedBookings.length === 0 && !showAddBooking ? (
            <p className="text-sm text-slate-400">No confirmed bookings yet.</p>
          ) : (
            <div className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-white">
              {confirmedBookings.map(b => (
                <div key={b.booking_id} className="px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-medium text-navy-900">{b.name ?? b.email}</p>
                        <AttendancePill status={b.attendance_status ?? null} />
                        {b.source === 'creator_manual' && (
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                            Manual
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-400">
                        {b.email}
                        {b.note && <span className="ml-2 text-slate-300">· {b.note}</span>}
                      </p>
                    </div>
                    {!isCancelled && (
                      <button
                        onClick={() => handleCancelBooking(b.booking_id)}
                        disabled={cancellingBookingId === b.booking_id}
                        className="shrink-0 text-xs text-slate-400 underline hover:text-slate-600 disabled:opacity-50"
                      >
                        {cancellingBookingId === b.booking_id ? 'Removing…' : 'Remove'}
                      </button>
                    )}
                  </div>
                  {/* Attendance marking — only available once the session has started */}
                  {!isCancelled && isPast && (
                    <AttendanceButtons
                      bookingId={b.booking_id}
                      eventId={event.id}
                      spaceSlug={spaceSlug}
                      currentStatus={b.attendance_status ?? null}
                      onUpdated={handleAttendanceUpdated}
                    />
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Cancelled bookings */}
          {cancelledBookings.length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-slate-400 hover:text-slate-600">
                {cancelledBookings.length} cancelled booking{cancelledBookings.length !== 1 ? 's' : ''}
              </summary>
              <div className="mt-2 divide-y divide-border overflow-hidden rounded-xl border border-border bg-white opacity-60">
                {cancelledBookings.map(b => (
                  <div key={b.booking_id} className="px-4 py-3">
                    <p className="text-sm line-through text-slate-400">{b.name ?? b.email}</p>
                    <p className="text-xs text-slate-300">{b.email}</p>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      {/* ── Danger zone ── */}
      {!isCancelled && (
        <div className="rounded-xl border border-red-100 bg-red-50/30 p-5">
          <p className="mb-1 text-sm font-semibold text-red-800">Danger zone</p>
          <p className="mb-4 text-xs text-red-600">
            Cancelling this session cannot be undone. Existing bookings are kept for your records.
          </p>
          {!showCancelConfirm ? (
            <button
              onClick={() => setShowCancelConfirm(true)}
              className="rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-700 transition-colors hover:bg-red-100"
            >
              Cancel this session
            </button>
          ) : (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-red-700">
                This cancels this session only. Other sessions in the series will not be changed.
              </p>
              {cancelError && <p className="text-xs text-red-500">{cancelError}</p>}
              <div className="flex gap-3">
                <button
                  onClick={handleCancelEvent}
                  disabled={cancelling}
                  className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {cancelling ? 'Cancelling…' : 'Yes, cancel this session'}
                </button>
                <button
                  onClick={() => { setShowCancelConfirm(false); setCancelError(null) }}
                  className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-slate-600 transition-colors hover:border-slate-400"
                >
                  Keep it
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {isCancelled && (
        <div className="rounded-xl border border-red-200 bg-red-50/50 p-5">
          <p className="text-sm font-semibold text-red-700">This session has been cancelled</p>
          <p className="mt-1 text-xs text-red-500">Booking and editing actions are disabled.</p>
        </div>
      )}
    </div>
  )
}
