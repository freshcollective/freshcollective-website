'use client'

import { useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { SeriesBookingResult } from '@/types/platform'

interface Props {
  eventId: string
  spaceSlug: string
  requiresBooking: boolean
  capacity: number | null
  initialBookedCount: number
  initialSpotsRemaining: number | null
  bookingNote: string | null
  initialMyBookingStatus: 'confirmed' | 'cancelled' | null
  initialCanBook: boolean
  initialCanCancelBooking: boolean
  isPast: boolean
  recurrenceSeriesId?: string | null
}

export default function BookingPanel({
  eventId,
  spaceSlug,
  requiresBooking,
  capacity,
  initialBookedCount,
  initialSpotsRemaining,
  bookingNote,
  initialMyBookingStatus,
  initialCanBook,
  initialCanCancelBooking,
  isPast,
  recurrenceSeriesId,
}: Props) {
  const [bookedCount, setBookedCount] = useState(initialBookedCount)
  const [spotsRemaining, setSpotsRemaining] = useState(initialSpotsRemaining)
  const [myBookingStatus, setMyBookingStatus] = useState(initialMyBookingStatus)
  const [canBook, setCanBook] = useState(initialCanBook)
  const [canCancelBooking, setCanCancelBooking] = useState(initialCanCancelBooking)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [seriesResult, setSeriesResult] = useState<SeriesBookingResult | null>(null)

  async function handleBook() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/events/${eventId}/book`), {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : 'Could not book spot.')
      }
      setMyBookingStatus('confirmed')
      setCanBook(false)
      setCanCancelBooking(true)
      setBookedCount((c) => c + 1)
      setSpotsRemaining((s) => (s !== null ? Math.max(0, s - 1) : null))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  async function handleCancelBooking() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/events/${eventId}/cancel-booking`), {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : 'Could not cancel booking.')
      }
      setMyBookingStatus('cancelled')
      setCanBook(true)
      setCanCancelBooking(false)
      setBookedCount((c) => Math.max(0, c - 1))
      setSpotsRemaining((s) => (s !== null ? s + 1 : null))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  async function handleBookSeries() {
    if (!recurrenceSeriesId) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/spaces/${spaceSlug}/events/series/${recurrenceSeriesId}/book`), {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : 'Could not book series.')
      }
      const result: SeriesBookingResult = await res.json()
      setSeriesResult(result)
      setMyBookingStatus('confirmed')
      setCanBook(false)
      setCanCancelBooking(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  if (!requiresBooking) return null

  const isBooked = myBookingStatus === 'confirmed'
  const isFull = spotsRemaining !== null && spotsRemaining === 0 && !isBooked

  return (
    <div>
      <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
        Booking
      </p>

      {isPast ? (
        <p className="mb-4 text-[15px] font-semibold text-navy-900">Session ended</p>
      ) : isBooked ? (
        <p className="mb-4 text-[15px] font-semibold text-teal-700">You&rsquo;re booked ✓</p>
      ) : isFull ? (
        <p className="mb-4 text-[15px] font-semibold text-slate-500">Session full</p>
      ) : (
        <p className="mb-4 text-[15px] font-semibold text-navy-900">Reserve your spot</p>
      )}

      <div className="mb-4 space-y-2 text-[13px] text-slate-500">
        {capacity !== null && (
          <div className="flex items-center justify-between">
            <span>Spots</span>
            <span className="font-medium text-navy-800">
              {spotsRemaining !== null ? `${spotsRemaining} of ${capacity} remaining` : `${capacity} total`}
            </span>
          </div>
        )}
        {bookedCount > 0 && (
          <div className="flex items-center justify-between">
            <span>Booked</span>
            <span className="font-medium text-navy-800">{bookedCount}</span>
          </div>
        )}
      </div>

      {/* Series booking result */}
      {seriesResult && (
        <div
          className="mb-3 rounded-xl px-4 py-3 text-[12px] text-teal-800"
          style={{ background: 'rgba(56,160,158,0.08)', border: '1px solid rgba(56,160,158,0.2)' }}
        >
          Booked {seriesResult.booked} session{seriesResult.booked !== 1 ? 's' : ''}.
          {seriesResult.skipped_full > 0 && ` ${seriesResult.skipped_full} full.`}
          {seriesResult.skipped_closed > 0 && ` ${seriesResult.skipped_closed} booking closed.`}
          {seriesResult.already_booked > 0 && ` ${seriesResult.already_booked} already booked.`}
        </div>
      )}

      {!isPast && (
        <>
          {isBooked ? (
            <div className="space-y-2">
              <div
                className="flex items-center gap-2 rounded-xl px-4 py-2.5"
                style={{ background: 'rgba(56,160,158,0.08)' }}
              >
                <span className="text-sm font-semibold text-teal-700">Booking confirmed</span>
              </div>
              {canCancelBooking && (
                <button
                  onClick={handleCancelBooking}
                  disabled={loading}
                  className="w-full rounded-xl border border-slate-200 py-2 text-sm text-slate-400 transition-colors hover:border-red-200 hover:text-red-500 disabled:opacity-50"
                >
                  {loading ? 'Cancelling…' : 'Cancel booking'}
                </button>
              )}
            </div>
          ) : canBook ? (
            <div className="space-y-2">
              <button
                onClick={handleBook}
                disabled={loading}
                className="w-full rounded-xl py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                {loading ? 'Booking…' : 'Book your spot'}
              </button>
              {recurrenceSeriesId && !seriesResult && (
                <button
                  onClick={handleBookSeries}
                  disabled={loading}
                  className="w-full rounded-xl border border-teal-200 py-2 text-sm font-medium text-teal-700 transition-colors hover:bg-teal-50 disabled:opacity-50"
                >
                  {loading ? 'Booking…' : 'Book remaining sessions'}
                </button>
              )}
            </div>
          ) : isFull ? (
            <button disabled className="w-full cursor-not-allowed rounded-xl bg-slate-100 py-2.5 text-sm font-semibold text-slate-400">
              Session full
            </button>
          ) : null}
        </>
      )}

      {bookingNote && (
        <p className="mt-3 text-[12px] leading-relaxed text-slate-400">{bookingNote}</p>
      )}

      {error && (
        <p className="mt-2 text-[12px] text-red-500">{error}</p>
      )}
    </div>
  )
}
