'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import { formatMoneyCents } from '@/lib/formatMoney'
import DiscountCodeField from '@/components/checkout/DiscountCodeField'
import {
  coveredByLabel,
  coveredHeading,
  ticketCardBlocksPurchase,
  ticketCardState,
} from '@/lib/gatheringPurchaseStatus'
import type { BookingOrigin } from '@/types/platform'

/**
 * GatheringTicketPurchaseClient
 *
 * Right-column panel for standalone paid Gatherings on the member
 * detail page. Owns the full purchase state machine end-to-end:
 *
 *   available         → Buy your ticket
 *   purchased         → You're in
 *   sales_disabled    → Ticket sales aren't open yet
 *   sold_out          → Sold out
 *   cancelled         → cancelled state (rendered by the parent)
 *   past              → past state (rendered by the parent)
 *   confirming        → Confirming your ticket… (polling after Stripe return)
 *   payment_cancelled → No-charge message (?checkout=cancelled)
 *
 * The button POSTs `/api/spaces/{slug}/events/{event_id}/checkout` and
 * redirects to the returned Stripe Checkout URL. `reused=true` responses
 * are transparently followed. Backend errors map to typed friendly copy.
 *
 * Nothing in this component grants access — it only reflects the
 * server's authoritative `my_booking_status`. Polling is bounded to
 * 30 seconds and stops on unmount.
 */

// ---------------------------------------------------------------------------
// Error map — every backend code we handle explicitly. Anything else falls
// through to the generic "couldn't open checkout" copy. We never surface a
// raw stripe error, a Session id, or a backend stack trace to the user.
// ---------------------------------------------------------------------------

const CHECKOUT_ERROR_COPY: Record<string, string> = {
  sales_disabled:              'Ticket sales aren\u2019t open yet.',
  sold_out:                    'This Gathering has just sold out.',
  already_has_ticket:          'You already have a ticket for this Gathering.',
  gathering_unavailable:       'Ticket sales are not available for this Gathering right now.',
  not_paid_gathering:          'This Gathering doesn\u2019t sell standalone tickets.',
  invalid_ticket_config:       'Ticket sales are not available for this Gathering right now.',
  stripe_error:                'We couldn\u2019t open checkout. Please try again.',
  stripe_not_configured:       'Ticket sales aren\u2019t open yet.',
}

const GENERIC_ERROR = 'We couldn\u2019t open checkout. Please try again.'

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  /** Stage 3E.2 — the surface already names this card.
   *
   *  Inside Ways to join the card carries the title "Individual
   *  ticket", so this component's own "Buy your ticket" heading sat
   *  above a button saying the same words. The state headings — sold
   *  out, ended, not yet open — are kept either way: those say
   *  something a label cannot. */
  headingProvided?: boolean
  spaceSlug: string
  eventId: string
  eventTitle: string
  priceCents: number | null
  currency: string | null
  salesEnabled: boolean
  isAuthenticated: boolean
  isPast: boolean
  isCancelled: boolean
  /** From EventSummary — 'confirmed' | 'cancelled' | 'pending_payment' | null */
  initialMyBookingStatus: 'confirmed' | 'cancelled' | 'pending_payment' | null
  /** Stage 4B — which arrangement produced that booking.
   *
   *  Without it this card read every place as its own, and announced
   *  "Payment in progress" for a Payment Option checkout started
   *  elsewhere. Omitted on surfaces with only one way in, where the
   *  question cannot arise. */
  bookingOrigin?: BookingOrigin | null
  /** Backend's max(0, capacity - confirmed - active_holds). null = unlimited */
  spotsRemaining: number | null
  capacity: number | null
  /** Stage 4 — whether this Collective's surface may offer a discount
   *  code. Resolved server-side from UNIVERSAL_DISCOUNT_CODES_ENABLED;
   *  defaults off so a caller that has not been taught to pass it shows
   *  no code box rather than one whose every submission is refused. */
  discountCodesEnabled?: boolean
}

export default function GatheringTicketPurchaseClient({
  spaceSlug, eventId, eventTitle, priceCents, currency,
  salesEnabled, isAuthenticated, isPast, isCancelled,
  initialMyBookingStatus, spotsRemaining, capacity,
  headingProvided = false,
  discountCodesEnabled = false,
  bookingOrigin = null,
}: Props) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const returnState = searchParams.get('checkout')  // 'success' | 'cancelled' | null

  const [myBookingStatus, setMyBookingStatus] =
    useState<Props['initialMyBookingStatus']>(initialMyBookingStatus)
  const [opening, setOpening] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Only ever a code. The amount is the server's business — see
  // ``DiscountCodeField``.
  const [discountCode, setDiscountCode] = useState<string | null>(null)

  // Interim "confirming your ticket…" state after Stripe returns success.
  // Set on mount when we see ?checkout=success AND the current booking
  // isn't yet 'confirmed'. Polling refreshes the router until it flips.
  const [pollTimeoutHit, setPollTimeoutHit] = useState(false)
  const [pollingActive, setPollingActive] = useState(false)
  const pollingRef = useRef<{ startedAt: number; cancelled: boolean } | null>(null)

  const isConfirmed = myBookingStatus === 'confirmed'

  // Stage 4B — what this card may claim.
  //
  // ``isConfirmed`` describes the member's *booking* and still drives
  // the polling below, which is about the booking. What this card is
  // allowed to say about itself is a narrower question: a place only
  // counts as this card's when this card's arrangement produced it.
  const cardState = ticketCardState(myBookingStatus, bookingOrigin)
  const showsPurchased = cardState === 'purchased'
  const showsPending = cardState === 'pending'
  const showsCovered = cardState === 'covered' || cardState === 'held_elsewhere'
  // A place is a place, however it was earned — so none of these may
  // offer a second one. §6E.
  const blocksPurchase = ticketCardBlocksPurchase(cardState)
  // The one exception: a ticket checkout *this card* started may still
  // be finished. ``blocksPurchase`` stops a second purchase; this
  // allows the first one to complete.
  const canOpenCheckout = cardState === 'available' || showsPending

  const isSoldOut =
    !blocksPurchase && capacity !== null && spotsRemaining !== null && spotsRemaining <= 0

  // ── Success return: start bounded polling if not yet confirmed ─────────
  useEffect(() => {
    if (returnState !== 'success') return
    if (isConfirmed) return
    if (pollingRef.current || pollTimeoutHit) return

    const state = { startedAt: Date.now(), cancelled: false }
    pollingRef.current = state
    setPollingActive(true)

    const tick = async () => {
      if (state.cancelled) return
      try {
        const r = await fetch(
          apiUrl(`/api/spaces/${spaceSlug}/events/${eventId}`),
          { credentials: 'include', cache: 'no-store' },
        )
        if (r.ok) {
          const data = await r.json()
          const status = data.my_booking_status as Props['initialMyBookingStatus']
          if (status === 'confirmed') {
            if (state.cancelled) return
            setMyBookingStatus('confirmed')
            setPollingActive(false)
            // Trigger a full server-side re-render so attendee-only
            // fields (meeting link, venue address, replay, resources)
            // populate from the fresh render, not from our fetch.
            router.refresh()
            return
          }
        }
      } catch {
        // Ignore transient network errors during polling.
      }

      const elapsed = Date.now() - state.startedAt
      if (elapsed >= 30_000) {
        setPollingActive(false)
        setPollTimeoutHit(true)
        return
      }
      setTimeout(tick, 2_500)
    }

    setTimeout(tick, 500)
    return () => {
      state.cancelled = true
      pollingRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [returnState, isConfirmed])

  // ── Buy your ticket click ─────────────────────────────────────────────
  const successUrl = typeof window !== 'undefined'
    ? `${window.location.origin}/spaces/${spaceSlug}/events/${eventId}?checkout=success`
    : `/spaces/${spaceSlug}/events/${eventId}?checkout=success`
  const cancelUrl = typeof window !== 'undefined'
    ? `${window.location.origin}/spaces/${spaceSlug}/events/${eventId}?checkout=cancelled`
    : `/spaces/${spaceSlug}/events/${eventId}?checkout=cancelled`

  const handleBuy = useCallback(async () => {
    if (opening) return
    setOpening(true)
    setError(null)
    try {
      const r = await fetch(
        apiUrl(`/api/spaces/${spaceSlug}/events/${eventId}/checkout`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            success_url: successUrl,
            cancel_url: cancelUrl,
            // Stage 4 — the code, never a price. The server resolves it
            // again against the ticket's own price, and the seat is
            // still decided on capacity rather than on money.
            ...(discountCode ? { discount_code: discountCode } : {}),
          }),
        },
      )
      if (!r.ok) {
        let code = 'generic'
        try {
          const body = await r.json()
          const detail = body?.detail
          if (typeof detail === 'object' && detail?.code) code = detail.code
          if (code === 'already_has_ticket') {
            // Backend says the user already has a confirmed booking — the
            // page state disagreed. Sync UI to reality and re-render.
            router.refresh()
          }
        } catch { /* leave code='generic' */ }
        setError(CHECKOUT_ERROR_COPY[code] ?? GENERIC_ERROR)
        setOpening(false)
        return
      }
      const data = await r.json() as { checkout_url: string; reused?: boolean }
      // `reused=true` means an in-flight Session already exists — we still
      // redirect to it, which naturally continues the buyer's checkout.
      window.location.href = data.checkout_url
    } catch {
      setError(GENERIC_ERROR)
      setOpening(false)
    }
    // ``discountCode`` is a dependency, not an incidental read: without
    // it this callback closes over whatever the code was when it was
    // last rebuilt, and a member who applied a code after the first
    // render would be charged full price while being shown a discount.
  }, [opening, spaceSlug, eventId, successUrl, cancelUrl, router, discountCode])

  // Signed-out: preserve a safe next URL and hand off to /login. We route
  // through login; login.tsx will surface the "Log in to buy your ticket
  // for [Gathering title]" line based on the next-URL shape.
  const nextForAuth = `/spaces/${spaceSlug}/events/${eventId}?checkout=return`
  const loginHref = `/login?next=${encodeURIComponent(nextForAuth)}`
  const signupHref = `/signup?next=${encodeURIComponent(nextForAuth)}`

  // ---------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------

  return (
    <div>
      <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
        Ticket
      </p>

      {/* Header state line */}
      {isCancelled ? (
        <p className="mb-4 text-[15px] font-semibold text-red-700">
          This Gathering has been cancelled
        </p>
      ) : isConfirmed ? (
        <p
          className="mb-4 text-[15px] font-semibold"
          style={{ color: 'var(--fc-accent, #0f766e)' }}
        >
          You&rsquo;re in.
        </p>
      ) : isPast ? (
        <p className="mb-4 text-[15px] font-semibold text-navy-900">
          This Gathering has ended
        </p>
      ) : isSoldOut ? (
        <p className="mb-4 text-[15px] font-semibold text-navy-900">Sold out</p>
      ) : !salesEnabled ? (
        <p className="mb-4 text-[15px] font-semibold text-navy-900">
          Ticket sales aren&rsquo;t open yet
        </p>
      ) : headingProvided ? null : (
        <p className="mb-4 text-[15px] font-semibold text-navy-900">
          Buy your ticket
        </p>
      )}

      {/* Price + availability.
          Stated rather than tabulated: "Price | A$45" over
          "Places | 5 of 10 remaining" was a two-column table for two
          facts, which reads as a form. The facts are unchanged. */}
      <div className="mb-4 space-y-1 text-[13px] text-black">
        {priceCents != null && currency && (
          <p className="text-[15px] font-semibold text-navy-900">
            {formatMoneyCents(priceCents, currency)} once
          </p>
        )}
        {capacity == null ? (
          <p>No capacity limit</p>
        ) : spotsRemaining != null && (
          <p>
            {spotsRemaining === 0
              ? 'Sold out'
              : `${spotsRemaining} place${spotsRemaining === 1 ? '' : 's'} remaining`}
          </p>
        )}
      </div>

      {/* ── Success return: interim confirming state ──────────────────── */}
      {returnState === 'success' && !isConfirmed && !pollTimeoutHit && (
        <div
          className="mb-3 rounded-xl px-4 py-3"
          style={{
            background: 'var(--fc-accent-tint, rgba(56,160,158,0.06))',
            border: '1px solid var(--fc-accent-line, rgba(56,160,158,0.20))',
          }}
        >
          <p
            className="text-sm font-semibold"
            style={{ color: 'var(--fc-accent, #0f766e)' }}
          >
            Confirming your ticket…
          </p>
          <p
            className="mt-1 text-[12.5px] leading-relaxed"
            style={{ color: 'var(--fc-accent, #0f766e)' }}
          >
            Payment has been received. We&rsquo;re confirming your place now.
          </p>
          {pollingActive && (
            <div className="mt-2 flex items-center gap-2">
              <span
                className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-t-transparent"
                style={{ borderColor: 'var(--fc-accent, #38A09E)', borderTopColor: 'transparent' }}
                aria-hidden
              />
              <span
                className="text-[11.5px]"
                style={{ color: 'var(--fc-accent, #0f766e)' }}
              >Checking…</span>
            </div>
          )}
        </div>
      )}

      {returnState === 'success' && !isConfirmed && pollTimeoutHit && (
        <div
          className="mb-3 rounded-xl px-4 py-3"
          style={{ background: 'rgba(212,176,72,0.10)', border: '1px solid rgba(212,176,72,0.30)' }}
        >
          <p className="text-sm font-semibold" style={{ color: '#8A6A15' }}>
            Your payment is still being confirmed.
          </p>
          <p className="mt-1 text-[12.5px] leading-relaxed" style={{ color: '#8A6A15' }}>
            You can refresh this page shortly. If payment succeeded, your access
            will appear automatically.
          </p>
        </div>
      )}

      {/* ── Cancel return: no-charge message ─────────────────────────── */}
      {returnState === 'cancelled' && !isConfirmed && (
        <div
          className="mb-3 rounded-xl px-4 py-3"
          style={{ background: 'rgba(148,163,184,0.10)', border: '1px solid rgba(148,163,184,0.30)' }}
        >
          <p className="text-sm font-semibold text-navy-800">
            Your payment wasn&rsquo;t completed.
          </p>
          <p className="mt-1 text-[12.5px] leading-relaxed text-black">
            Your card has not been charged and your place has not been confirmed.
          </p>
        </div>
      )}

      {/* ── Confirmed: You're in card ─────────────────────────────────── */}
      {showsPurchased && (
        <div
          className="mb-3 rounded-xl px-4 py-3"
          style={{
            background: 'var(--fc-accent-soft, rgba(56,160,158,0.08))',
            border: '1px solid var(--fc-accent-line, rgba(56,160,158,0.15))',
          }}
        >
          <p
            className="text-sm font-semibold"
            style={{ color: 'var(--fc-accent, #0f766e)' }}
          >Ticket purchased</p>
          <p
            className="mt-1 text-[12.5px] leading-relaxed"
            style={{ color: 'var(--fc-accent, #0f766e)' }}
          >
            Your ticket is confirmed and your place has been reserved.
          </p>
        </div>
      )}

      {/* ── Pending payment (rare — user closed Stripe with a live hold) ── */}
      {showsPending && returnState !== 'success' && returnState !== 'cancelled' && (
        <div
          className="mb-3 rounded-xl px-4 py-3"
          style={{ background: 'rgba(212,176,72,0.10)', border: '1px solid rgba(212,176,72,0.30)' }}
        >
          <p className="text-sm font-semibold" style={{ color: '#8A6A15' }}>
            Payment in progress
          </p>
          <p className="mt-1 text-[12.5px] leading-relaxed" style={{ color: '#8A6A15' }}>
            Complete your payment to confirm your place. Use the button below to
            continue checkout.
          </p>
        </div>
      )}

      {/* ── A place earned elsewhere ──────────────────────────────────
          The member is going; this card simply did not sell them the
          seat. Said plainly, and with the arrangement named where
          there is a name worth giving, so the page stops implying they
          bought a ticket they did not buy — and stops offering them a
          second one. */}
      {showsCovered && (
        <div
          className="mb-3 rounded-xl px-4 py-3"
          style={{
            background: 'var(--fc-accent-soft, rgba(56,160,158,0.08))',
            border: '1px solid var(--fc-accent-line, rgba(56,160,158,0.15))',
          }}
        >
          <p
            className="text-sm font-semibold"
            style={{ color: 'var(--fc-accent, #0f766e)' }}
          >
            {coveredHeading(cardState)}
          </p>
          {coveredByLabel(bookingOrigin) && (
            <p
              className="mt-1 text-[12.5px] leading-relaxed"
              style={{ color: 'var(--fc-accent, #0f766e)' }}
            >
              {coveredByLabel(bookingOrigin)}
            </p>
          )}
          <p
            className="mt-1 text-[12.5px] leading-relaxed"
            style={{ color: 'var(--fc-accent, #0f766e)' }}
          >
            {cardState === 'covered'
              ? 'You don\u2019t need a separate ticket for this Gathering.'
              : 'We\u2019re holding your place while that checkout is completed.'}
          </p>
        </div>
      )}

      {/* ── Sold out ─────────────────────────────────────────────────── */}
      {!blocksPurchase && !isCancelled && !isPast && isSoldOut && (
        <button
          disabled
          className="w-full cursor-not-allowed rounded-xl bg-slate-100 py-2.5 text-sm font-semibold text-slate-400"
        >
          Sold out
        </button>
      )}

      {/* ── Sales disabled ────────────────────────────────────────────── */}
      {!blocksPurchase && !isCancelled && !isPast && !isSoldOut && !salesEnabled && (
        <div className="text-[12.5px] leading-relaxed text-black">
          This Gathering is being prepared for ticket sales. Check back soon.
        </div>
      )}

      {/* ── Signed-out purchase → auth ────────────────────────────────── */}
      {!blocksPurchase && !isCancelled && !isPast && !isSoldOut && salesEnabled && !isAuthenticated && (
        <div className="space-y-2">
          <Link
            href={loginHref}
            className="block w-full rounded-xl py-2.5 text-center text-sm font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
          >
            Log in to buy your ticket
          </Link>
          <p className="text-center text-[12px] text-black">
            New to Fresh Collective?{' '}
            <Link
              href={signupHref}
              className="font-medium hover:underline"
              style={{ color: 'var(--fc-accent, #0f766e)' }}
            >
              Join us
            </Link>
          </p>
        </div>
      )}

      {/* ── Signed-in: Buy your ticket ────────────────────────────────── */}
      {/* Stage 4 — the code box sits above the button, and only on the
          path that actually opens a checkout. A member continuing an
          existing pending payment is returning to a Session whose amount
          is already fixed, so offering a code there would imply it could
          still change the price. */}
      {discountCodesEnabled && !blocksPurchase && !isCancelled && !isPast
        && !isSoldOut && salesEnabled && isAuthenticated && (
        <div className="mb-2">
          <DiscountCodeField
            target={{ kind: 'gathering', targetId: eventId }}
            onChange={setDiscountCode}
            disabled={opening}
          />
        </div>
      )}
      {canOpenCheckout && !isCancelled && !isPast && !isSoldOut && salesEnabled && isAuthenticated && (
        <button
          type="button"
          onClick={handleBuy}
          disabled={opening}
          className="w-full rounded-xl py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
          style={{ background: 'linear-gradient(135deg, var(--fc-accent, #38A09E) 0%, var(--fc-accent-strong, #55B8B6) 100%)' }}
        >
          {opening ? 'Opening checkout…' : (showsPending ? 'Continue checkout' : 'Buy your ticket')}
        </button>
      )}

      {error && (
        <p className="mt-2 text-[12.5px] text-red-600">{error}</p>
      )}

      {!blocksPurchase && !isCancelled && !isPast && salesEnabled && (
        <p className="mt-3 text-[12px] leading-relaxed text-black">
          Your ticket reserves one place and gives you access to this Gathering only.
        </p>
      )}
    </div>
  )
}
