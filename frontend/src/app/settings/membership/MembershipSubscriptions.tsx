'use client'

/**
 * What the member pays to belong, and what they can do about it.
 *
 * Replaces the "coming soon" placeholder on Account Settings →
 * Membership. One card per Collective, and each card says only what
 * the backend says — the amount is the agreement's own, never the
 * Collective's current list price, so a member who joined at A$29
 * keeps reading A$29 after the creator moves to A$39.
 *
 * The distinction this component works hardest to keep
 * -----------------------------------------------------
 * **Cancelling renewal is not leaving.** They are different actions
 * with different consequences, in different places: cancelling stops
 * the next payment and keeps access to the end of the paid period;
 * leaving ends access now and lives on the Collectives list above.
 * The copy here names the date access actually runs to, and says
 * plainly that the member stays a member until then — because the
 * fear that cancelling throws you out immediately is exactly what
 * makes people not cancel, and then resent the charge.
 */

import { useCallback, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import { formatDay, formatRecurring, offerPhrase } from '@/lib/membership'
import SubscribeButton from '@/components/membership/SubscribeButton'
import type { MembershipState } from '@/types/platform'

const CARD = 'overflow-hidden rounded-2xl border border-border bg-white px-6 py-5'
const CARD_SHADOW = { boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }

const PRIMARY = 'inline-flex items-center justify-center rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60'
const PRIMARY_STYLE = {
  background: 'linear-gradient(135deg, #126E6C 0%, #17807E 100%)',
}
const QUIET = 'inline-flex items-center justify-center rounded-xl border border-slate-200 px-4 py-2 text-[13px] font-medium text-black transition-colors hover:bg-slate-50 disabled:opacity-60'

function Pill({ tone, children }: {
  tone: 'ok' | 'warn' | 'quiet'
  children: React.ReactNode
}) {
  const styles = {
    ok: 'bg-teal-50 text-teal-700 border-teal-200',
    warn: 'bg-[#FBEDE9] text-[#8C3F2E] border-[#E6C4BA]',
    quiet: 'bg-slate-50 text-slate-500 border-slate-200',
  }[tone]
  return (
    <span className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${styles}`}>
      {children}
    </span>
  )
}

export default function MembershipSubscriptions({
  rows,
}: {
  rows: MembershipState[]
}) {
  const router = useRouter()
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)

  const act = useCallback(async (
    slug: string, path: string, body?: Record<string, unknown>,
  ) => {
    setBusy(slug)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/spaces/${slug}/membership/${path}`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body ?? {}),
      })
      const payload = await res.json().catch(() => ({}))
      if (!res.ok) {
        const d = payload?.detail
        setError(typeof d === 'string' ? d
          : (d as { message?: string })?.message
          ?? 'That didn’t work. Please try again.')
        return null
      }
      return payload
    } catch {
      setError('We couldn’t reach the server. Please try again.')
      return null
    } finally {
      setBusy(null)
    }
  }, [])

  const updateCard = useCallback(async (slug: string) => {
    const origin = window.location.origin
    const back = `${origin}/checkout/membership?collective=${slug}`
    const payload = await act(slug, 'payment-method', {
      success_url: `${back}&pm_session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${origin}/settings/membership`,
    })
    if (payload?.checkout_url) window.location.href = payload.checkout_url
  }, [act])

  if (rows.length === 0) {
    return (
      <div className={`${CARD} py-8 text-center`} style={CARD_SHADOW}>
        <p className="text-[14px] text-black">
          You don’t pay for membership of any collective.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {error && (
        <p className="text-[13px] font-medium text-[#B0503C]">{error}</p>
      )}
      {rows.map((row) => {
        const { space, subscription: sub, actions, transition } = row
        const working = busy === space.slug
        const price = sub
          ? formatRecurring(sub.amount_cents, sub.currency, sub.interval, sub.interval_count)
          : offerPhrase(row)

        return (
          <div key={space.id} className={CARD} style={CARD_SHADOW}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <Link
                  href={`/spaces/${space.slug}`}
                  className="text-[14px] font-medium text-navy-800 transition-colors hover:text-teal-700"
                >
                  {space.name}
                </Link>
                {price && (
                  <p className="mt-0.5 text-[13px] text-black">{price}</p>
                )}
              </div>
              {sub?.status === 'active' && <Pill tone="ok">Active</Pill>}
              {sub?.status === 'past_due' && <Pill tone="warn">Payment problem</Pill>}
              {sub?.status === 'cancel_scheduled' && <Pill tone="quiet">Ending</Pill>}
              {sub?.status === 'pending' && <Pill tone="quiet">Not finished</Pill>}
              {(sub?.status === 'ended' || sub?.status === 'cancelled') && (
                <Pill tone="quiet">Ended</Pill>
              )}
              {!sub && transition.action_needed && (
                <Pill tone="warn">Subscription needed</Pill>
              )}
            </div>

            <div className="mt-3 text-[13px] leading-relaxed text-black">
              {/* Active and renewing. */}
              {sub?.status === 'active' && sub.renews_at && (
                <p>Next payment: {formatDay(sub.renews_at)}.</p>
              )}

              {/* Cancelled, but still inside the paid period. The
                  sentence a cancelling member most needs to read. */}
              {sub?.status === 'cancel_scheduled' && (
                <p>
                  <strong className="font-semibold text-navy-900">
                    Your membership is active until{' '}
                    {formatDay(sub.access_until) ?? 'the end of your paid period'}.
                  </strong>{' '}
                  Your subscription won’t renew, and you won’t be charged
                  again. You can keep using {space.name} until then.
                </p>
              )}

              {/* Recovery. Access continues — saying otherwise would
                  frighten somebody whose card simply expired. */}
              {sub?.status === 'past_due' && (
                <p>
                  <strong className="font-semibold text-navy-900">
                    We couldn’t process your membership payment.
                  </strong>{' '}
                  Your membership stays active while we try again
                  {sub.grace_expires_at
                    ? `, until ${formatDay(sub.grace_expires_at)}`
                    : ''}
                  . Updating your payment method is the quickest fix.
                </p>
              )}

              {sub?.status === 'pending' && (
                <p>
                  You started joining {space.name} but the payment wasn’t
                  finished, so there’s no membership yet and nothing has
                  been charged.
                </p>
              )}

              {(sub?.status === 'ended' || sub?.status === 'cancelled') && (
                <p>
                  <strong className="font-semibold text-navy-900">
                    Your paid membership has ended.
                  </strong>{' '}
                  Anything you bought separately is still yours.
                </p>
              )}

              {/* No agreement, but one is going to be needed. */}
              {!sub && transition.action_needed && (
                <p>
                  {transition.has_passed
                    ? `${space.name} now needs a paid membership.`
                    : `Membership payment required from ${formatDay(transition.effective_at)}.`}{' '}
                  Subscribe to keep access to members-only experiences.
                  Your history and anything you’ve bought separately stay
                  as they are.
                </p>
              )}
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              {actions.can_update_payment_method && (
                <button
                  type="button"
                  onClick={() => void updateCard(space.slug)}
                  disabled={working}
                  className={sub?.status === 'past_due' ? PRIMARY : QUIET}
                  style={sub?.status === 'past_due' ? PRIMARY_STYLE : undefined}
                >
                  Update payment method
                </button>
              )}

              {actions.can_resume && (
                <button
                  type="button"
                  onClick={async () => {
                    if (await act(space.slug, 'resume')) router.refresh()
                  }}
                  disabled={working}
                  className={PRIMARY}
                  style={PRIMARY_STYLE}
                >
                  Resume renewal
                </button>
              )}

              {actions.can_cancel_renewal && confirming !== space.slug && (
                <button
                  type="button"
                  onClick={() => setConfirming(space.slug)}
                  disabled={working}
                  className={QUIET}
                >
                  Cancel renewal
                </button>
              )}

              {actions.can_subscribe && (!sub || sub.status !== 'pending') && (
                <SubscribeButton
                  slug={space.slug}
                  label={sub ? 'Subscribe again' : 'Subscribe'}
                  className={PRIMARY}
                  style={PRIMARY_STYLE}
                />
              )}

              {actions.can_continue_checkout && (
                <SubscribeButton
                  slug={space.slug}
                  label="Continue checkout"
                  className={PRIMARY}
                  style={PRIMARY_STYLE}
                />
              )}
            </div>

            {/* Confirmation, with the consequence spelled out — and
                the distinction from leaving made explicit, because
                this is the moment a member fears getting it wrong. */}
            {confirming === space.slug && (
              <div
                className="mt-3 rounded-xl border px-4 py-3"
                style={{ borderColor: '#E6C4BA', background: '#FBEDE9' }}
              >
                <p className="text-[13px] leading-relaxed text-navy-900">
                  Stop renewing your membership of {space.name}?
                  {sub?.current_period_end && (
                    <>
                      {' '}You’ll keep access until{' '}
                      <strong className="font-semibold">
                        {formatDay(sub.current_period_end)}
                      </strong>
                      , and you won’t be charged again.
                    </>
                  )}{' '}
                  This isn’t the same as leaving — you stay a member
                  until then, and nothing you’ve bought separately is
                  affected.
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={async () => {
                      if (await act(space.slug, 'cancel')) {
                        setConfirming(null)
                        router.refresh()
                      }
                    }}
                    disabled={working}
                    className={PRIMARY}
                    style={PRIMARY_STYLE}
                  >
                    {working ? 'Cancelling…' : 'Yes, stop renewing'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirming(null)}
                    disabled={working}
                    className={QUIET}
                  >
                    Keep my membership
                  </button>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
