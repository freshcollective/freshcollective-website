'use client'

/**
 * What actually happened, asked of the backend rather than the URL.
 *
 * A Stripe `success_url` means the member finished Stripe's form. It
 * does not mean the first invoice was paid, and it certainly does not
 * mean membership was granted — that happens when a verified invoice
 * reaches `activate_from_first_invoice`, which may be a second or two
 * behind the redirect. So this page claims nothing on arrival: it
 * polls the member's own state until the backend says the agreement
 * is active, and says "processing" until then.
 *
 * The honest failure is a timeout, not a lie. If the webhook has not
 * landed within the window the page still refuses to claim success —
 * it tells the member their payment is being confirmed and gives them
 * somewhere to go.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import { formatDay, formatRecurring } from '@/lib/membership'
import type { MembershipState } from '@/types/platform'

type Phase = 'checking' | 'active' | 'processing' | 'unpaid' | 'cancelled' | 'error'

/** How long to wait for a webhook before saying so plainly. */
const ATTEMPTS = 10
const INTERVAL_MS = 1500

export default function MembershipReturnFlow({
  slug, outcome, paymentMethodSessionId,
}: {
  slug: string
  outcome: string | null
  paymentMethodSessionId: string | null
}) {
  const [state, setState] = useState<MembershipState | null>(null)
  const [phase, setPhase] = useState<Phase>(
    outcome === 'cancelled' ? 'cancelled' : 'checking',
  )
  // 'refused'  — we declined before touching Stripe, so nothing changed.
  // 'unknown'   — the request failed after Stripe may already have acted.
  //               On 22 November a 500 here was reported as "nothing was
  //               changed" while the card had in fact been accepted, so the
  //               two are no longer the same state.
  const [pmResult, setPmResult] = useState<
    'idle' | 'ok' | 'pending' | 'refused' | 'unknown'
  >('idle')
  const cancelled = useRef(false)

  const read = useCallback(async (): Promise<MembershipState | null> => {
    const res = await fetch(apiUrl(`/api/spaces/${slug}/membership/state`), {
      credentials: 'include', cache: 'no-store',
    })
    if (!res.ok) return null
    return res.json() as Promise<MembershipState>
  }, [slug])

  // The card-change return. Confirmed server-side against Stripe
  // before anything is believed.
  useEffect(() => {
    if (!paymentMethodSessionId) return
    let gone = false
    void (async () => {
      try {
        const res = await fetch(
          apiUrl(`/api/spaces/${slug}/membership/payment-method/confirm`),
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ session_id: paymentMethodSessionId }),
          },
        )
        if (gone) return
        if (!res.ok) {
          // A 409 is our own refusal — the Session did not belong to
          // this agreement, or there was nothing to update — and it is
          // raised before Stripe is asked to change anything. Anything
          // else leaves the outcome genuinely unknown.
          setPmResult(res.status === 409 ? 'refused' : 'unknown')
          return
        }
        const body = await res.json().catch(() => ({}))
        setPmResult(body?.updated ? 'ok' : 'pending')
      } catch {
        // The request never completed. Stripe may have acted anyway.
        if (!gone) setPmResult('unknown')
      }
    })()
    return () => { gone = true }
  }, [paymentMethodSessionId, slug])

  useEffect(() => {
    if (outcome === 'cancelled') return
    cancelled.current = false
    void (async () => {
      for (let i = 0; i < ATTEMPTS; i += 1) {
        if (cancelled.current) return
        const next = await read()
        if (cancelled.current) return
        if (next) {
          setState(next)
          const status = next.subscription?.status
          if (status === 'active' || status === 'cancel_scheduled') {
            setPhase('active')
            return
          }
          if (status === 'failed') { setPhase('unpaid'); return }
        }
        setPhase('processing')
        await new Promise((r) => setTimeout(r, INTERVAL_MS))
      }
      // Still nothing. Say that, rather than promoting a guess.
      setPhase('processing')
    })()
    return () => { cancelled.current = true }
  }, [outcome, read])

  const sub = state?.subscription ?? null
  const name = state?.space.name ?? 'this collective'
  const card = 'rounded-2xl border border-border bg-white px-6 py-7'

  const backToCollective = (
    <Link
      href={`/spaces/${slug}`}
      className="mt-5 inline-flex rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white"
      style={{ background: 'linear-gradient(135deg, #126E6C 0%, #17807E 100%)' }}
    >
      Go to {name}
    </Link>
  )

  return (
    <div className="mx-auto max-w-[560px]">
      {paymentMethodSessionId && (
        <div className={`${card} mb-4`}>
          <h1 className="text-[20px] font-semibold text-navy-900">
            {pmResult === 'ok' ? 'Payment method updated'
              : pmResult === 'refused' ? 'We couldn’t update your payment method'
              : pmResult === 'unknown' ? 'We couldn’t confirm your payment method'
              : 'Updating your payment method…'}
          </h1>
          <p className="mt-2 text-[14px] leading-relaxed text-black">
            {pmResult === 'ok'
              ? `Future payments for ${name} will use your new card. Nothing else you pay for has changed.`
              : pmResult === 'pending'
              ? 'Stripe hasn’t finished confirming the card yet. Give it a moment and check your membership settings.'
              : pmResult === 'refused'
              ? 'Nothing was changed. You can try again from your membership settings.'
              : pmResult === 'unknown'
              ? `Your card may already have been updated. Please check your membership settings before trying again — if ${name} still shows the old card, you can start again from there.`
              : 'One moment.'}
          </p>
          <Link
            href="/settings/membership"
            className="mt-4 inline-block text-[13px] font-semibold text-teal-700 hover:underline"
          >
            Go to membership settings →
          </Link>
        </div>
      )}

      {!paymentMethodSessionId && (
        <div className={card}>
          {phase === 'cancelled' && (
            <>
              <h1 className="text-[20px] font-semibold text-navy-900">
                Checkout cancelled
              </h1>
              <p className="mt-2 text-[14px] leading-relaxed text-black">
                Nothing was charged and nothing has changed. You can join
                {' '}{name} whenever you’re ready.
              </p>
              <Link
                href={`/spaces/${slug}/about`}
                className="mt-4 inline-block text-[13px] font-semibold text-teal-700 hover:underline"
              >
                Back to {name} →
              </Link>
            </>
          )}

          {(phase === 'checking' || phase === 'processing') && (
            <>
              <h1 className="text-[20px] font-semibold text-navy-900">
                Confirming your payment
              </h1>
              <p className="mt-2 text-[14px] leading-relaxed text-black">
                Your card details are with Stripe and we’re waiting for
                confirmation. This usually takes a few seconds.{' '}
                <strong className="font-semibold text-navy-900">
                  Your membership starts once the payment is confirmed
                </strong>
                {' '}— not before, so there’s nothing to do here.
              </p>
              <p className="mt-2 text-[13px] leading-relaxed text-black">
                You can safely leave this page. Your membership will
                appear in your settings once it’s through.
              </p>
              <Link
                href="/settings/membership"
                className="mt-4 inline-block text-[13px] font-semibold text-teal-700 hover:underline"
              >
                Go to membership settings →
              </Link>
            </>
          )}

          {phase === 'active' && sub && (
            <>
              <h1 className="text-[20px] font-semibold text-navy-900">
                Your membership is active
              </h1>
              <p className="mt-2 text-[14px] leading-relaxed text-black">
                {formatRecurring(
                  sub.amount_cents, sub.currency, sub.interval,
                  sub.interval_count,
                )}
                {sub.is_one_time
                  ? '. There are no recurring payments.'
                  : sub.renews_at
                  // The Collective's timezone, the same one Account
                  // Settings and the emails use. Without it this page
                  // fell back to the reader's own zone and could name a
                  // different day for the same payment.
                  ? `. Next payment: ${formatDay(
                      sub.renews_at, state?.space.timezone,
                    )}.`
                  : '.'}
              </p>
              {backToCollective}
            </>
          )}

          {phase === 'unpaid' && (
            <>
              <h1 className="text-[20px] font-semibold text-navy-900">
                Payment unsuccessful
              </h1>
              <p className="mt-2 text-[14px] leading-relaxed text-black">
                Your card wasn’t charged and your membership hasn’t
                started. You can try again whenever you like.
              </p>
              <Link
                href={`/spaces/${slug}/about`}
                className="mt-4 inline-block text-[13px] font-semibold text-teal-700 hover:underline"
              >
                Back to {name} →
              </Link>
            </>
          )}
        </div>
      )}
    </div>
  )
}
