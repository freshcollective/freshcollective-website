'use client'

import { useState } from 'react'
import Link from 'next/link'
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
  accessType?: 'all_members' | 'pathway_required'
  userHasPathwayAccess?: boolean
  /** Full booking access-type string from the API response. Used to
   *  branch the UI for ``included_with_series`` — the Series-pass
   *  booking flow explains the pass requirement rather than exposing
   *  a broken purchase link (Offer Page purchase surface is a
   *  future milestone). */
  bookingAccessType?: string
  /** Optional Series title, when the Event belongs to one. Used in
   *  the pass-required explainer copy. */
  seriesTitle?: string | null
  /** True when the viewer holds a valid pass for the Event's Series.
   *  Lets us render the correct state without a speculative POST. */
  userHasSeriesPass?: boolean
  isAuthenticated: boolean
  loginHref: string
}

export default function GatheringBookingClient({
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
  accessType = 'all_members',
  userHasPathwayAccess = true,
  bookingAccessType,
  seriesTitle,
  userHasSeriesPass = false,
  isAuthenticated,
  loginHref,
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
        throw new Error(typeof b.detail === 'string' ? b.detail : 'Could not reserve your place.')
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
      const res = await fetch(
        apiUrl(`/api/spaces/${spaceSlug}/events/${eventId}/cancel-booking`),
        { method: 'POST', credentials: 'include' },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : 'Could not release your place.')
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
      const res = await fetch(
        apiUrl(`/api/spaces/${spaceSlug}/events/series/${recurrenceSeriesId}/book`),
        { method: 'POST', credentials: 'include' },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : 'Could not reserve the series.')
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

  const isReserved = myBookingStatus === 'confirmed'
  const isFull = spotsRemaining !== null && spotsRemaining === 0 && !isReserved
  const needsPathwayAccess = accessType === 'pathway_required' && !userHasPathwayAccess
  const isSeriesGated = bookingAccessType === 'included_with_series'

  return (
    <div>
      <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
        Your place
      </p>

      {isPast ? (
        <p className="mb-4 text-[15px] font-semibold text-navy-900">This Gathering has ended</p>
      ) : isReserved ? (
        <p className="mb-4 text-[15px] font-semibold text-teal-700">You&rsquo;ve reserved your place ✓</p>
      ) : isFull ? (
        <p className="mb-4 text-[15px] font-semibold text-black">All places taken</p>
      ) : (
        <p className="mb-4 text-[15px] font-semibold text-navy-900">Reserve your place</p>
      )}

      <div className="mb-4 space-y-2 text-[13px] text-black">
        {capacity !== null && (
          <div className="flex items-center justify-between">
            <span>Places</span>
            <span className="font-medium text-navy-800">
              {spotsRemaining !== null
                ? `${spotsRemaining} of ${capacity} remaining`
                : `${capacity} total`}
            </span>
          </div>
        )}
        {bookedCount > 0 && (
          <div className="flex items-center justify-between">
            <span>Reserved</span>
            <span className="font-medium text-navy-800">{bookedCount}</span>
          </div>
        )}
      </div>

      {seriesResult && (
        <div
          className="mb-3 rounded-xl px-4 py-3 text-[12px] text-teal-800"
          style={{ background: 'rgba(56,160,158,0.08)', border: '1px solid rgba(56,160,158,0.2)' }}
        >
          Reserved a place in {seriesResult.booked} Gathering{seriesResult.booked !== 1 ? 's' : ''}.
          {seriesResult.skipped_full > 0 && ` ${seriesResult.skipped_full} full.`}
          {seriesResult.skipped_closed > 0 && ` ${seriesResult.skipped_closed} closed to new places.`}
          {seriesResult.already_booked > 0 && ` ${seriesResult.already_booked} already reserved.`}
        </div>
      )}

      {!isPast && !isAuthenticated && (
        <Link
          href={loginHref}
          className="block w-full rounded-xl py-2.5 text-center text-sm font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Sign in to reserve
        </Link>
      )}

      {!isPast && isAuthenticated && needsPathwayAccess && (
        <button
          disabled
          className="w-full cursor-not-allowed rounded-xl bg-slate-100 py-2.5 text-sm font-semibold text-slate-400"
        >
          Join the Pathway to reserve
        </button>
      )}

      {/* Series-pass access, no valid pass — explain what's needed.
          Deliberately renders no purchase link; the Offer Page will
          become the purchase surface in a later milestone. This
          keeps the current state honest ("here's what you need")
          without exposing a 404 route to a not-yet-built purchase
          flow. */}
      {!isPast && isAuthenticated && isSeriesGated && !isReserved && !userHasSeriesPass && (
        <div
          className="rounded-xl px-4 py-3"
          style={{ background: 'rgba(214,177,63,0.08)', border: '1px solid rgba(214,177,63,0.30)' }}
        >
          <p className="text-[13.5px] font-semibold text-navy-900">
            {seriesTitle ? `A ${seriesTitle} pass is required` : 'A Series pass is required'}
          </p>
          <p className="mt-1 text-[12.5px] leading-relaxed" style={{ color: 'rgba(12,24,38,0.65)' }}>
            This session is reserved with a valid pass for the
            Gathering Series. Ways to join will be available shortly.
          </p>
        </div>
      )}

      {!isPast && isAuthenticated && !needsPathwayAccess && !(isSeriesGated && !userHasSeriesPass) && (
        <>
          {isReserved ? (
            <div className="space-y-2">
              <div
                className="rounded-xl px-4 py-3"
                style={{ background: 'rgba(56,160,158,0.08)', border: '1px solid rgba(56,160,158,0.15)' }}
              >
                <p className="text-sm font-semibold text-teal-700">You&rsquo;re in.</p>
                <p className="mt-1 text-[12.5px] leading-relaxed text-teal-800">
                  We&rsquo;ve saved your place and you&rsquo;ll find this Gathering
                  in your upcoming schedule.
                </p>
              </div>
              {canCancelBooking && (
                <button
                  onClick={handleCancelBooking}
                  disabled={loading}
                  className="w-full rounded-xl border border-slate-200 py-2 text-sm text-black transition-colors hover:border-red-200 hover:text-red-500 disabled:opacity-50"
                >
                  {loading ? 'Releasing…' : 'Release your place'}
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
                {loading ? 'Reserving…' : 'Reserve your place'}
              </button>
              {recurrenceSeriesId && !seriesResult && !isSeriesGated && (
                <button
                  onClick={handleBookSeries}
                  disabled={loading}
                  className="w-full rounded-xl border border-teal-200 py-2 text-sm font-medium text-teal-700 transition-colors hover:bg-teal-50 disabled:opacity-50"
                >
                  {loading ? 'Reserving\u2026' : 'Reserve every Gathering in this series'}
                </button>
              )}
            </div>
          ) : isFull ? (
            <button
              disabled
              className="w-full cursor-not-allowed rounded-xl bg-slate-100 py-2.5 text-sm font-semibold text-slate-400"
            >
              All places taken
            </button>
          ) : null}
        </>
      )}

      {bookingNote && (
        <p className="mt-3 text-[12px] leading-relaxed text-black">{bookingNote}</p>
      )}

      {error && <p className="mt-2 text-[12px] text-red-500">{error}</p>}
    </div>
  )
}
