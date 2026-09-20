'use client'

import { useState } from 'react'
import Link from 'next/link'

import { apiUrl } from '@/lib/api'
import type { JoiningOption } from '@/types/platform'

/**
 * Ways into a Collective that cannot be joined for free.
 *
 * Each option leads into the same ``POST /api/checkout`` every other
 * purchase on the platform uses — the one that creates the Stripe
 * session, records the transaction, grants whatever the option's
 * grants say, and brings the buyer into the Collective. Deliberately
 * not ``/checkout/member``, which is a prototype that takes no money
 * and grants nothing.
 *
 * Buying here is not a separate "membership purchase". It is the
 * ordinary purchase of a term, a pathway or a pass, which happens to
 * be the door: one payment, one fulfilment, membership and access
 * together.
 */

function formatPrice(cents: number | null, currency: string): string | null {
  if (cents == null) return null
  if (cents === 0) return 'Free'
  return `$${(cents / 100).toLocaleString('en-AU', {
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  })} ${currency}`
}

export default function JoiningDoors({
  slug,
  options,
  isLoggedIn,
}: {
  slug: string
  options: JoiningOption[]
  isLoggedIn: boolean
}) {
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // No doors is a real answer, never a reason to fall back to a free
  // join. The creator has either not nominated an option yet or has
  // unpublished the ones they had; a visitor should be told plainly
  // rather than shown a button that cannot work.
  if (options.length === 0) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-center">
        <p className="text-[13px] font-medium text-slate-600">
          Not open for new members right now
        </p>
        <p className="mt-1 text-[12px] text-slate-500">
          Check back soon, or get in touch with the collective.
        </p>
      </div>
    )
  }

  if (!isLoggedIn) {
    return (
      <div className="flex flex-col gap-2">
        <Link
          href={`/login?next=/spaces/${slug}/about`}
          className="rounded-xl px-4 py-2.5 text-center text-[13px] font-semibold text-white"
          style={{ background: 'var(--fc-accent, #38A09E)' }}
        >
          Sign in to join
        </Link>
        <p className="text-center text-[12px] text-black">
          Membership comes with your first purchase.
        </p>
      </div>
    )
  }

  async function startCheckout(optionId: string) {
    setBusyId(optionId)
    setError(null)
    try {
      const base = `${window.location.origin}/spaces/${slug}/about`
      const res = await fetch(apiUrl('/api/checkout'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          payment_option_id: optionId,
          success_url: `${base}?checkout=success`,
          cancel_url: `${base}?checkout=cancel`,
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(
          typeof body.detail === 'string'
            ? body.detail
            : `Could not start checkout (${res.status})`,
        )
      }
      const data = (await res.json()) as { checkout_url: string }
      window.location.href = data.checkout_url
    } catch (err) {
      setError(String((err as Error)?.message ?? err))
      setBusyId(null)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {options.map((option) => {
        const price = formatPrice(option.price_cents, option.currency)
        return (
          <button
            key={option.id}
            type="button"
            disabled={busyId !== null}
            onClick={() => void startCheckout(option.id)}
            className="flex w-full flex-col items-stretch gap-0.5 rounded-xl px-4 py-2.5 text-left transition-opacity hover:opacity-90 disabled:opacity-60"
            style={{ background: 'var(--fc-accent, #38A09E)' }}
          >
            <span className="flex items-center justify-between gap-3">
              <span className="text-[13px] font-semibold text-white">
                {busyId === option.id ? 'Starting…' : option.name}
              </span>
              {price && (
                <span className="shrink-0 text-[13px] font-semibold text-white">
                  {price}
                </span>
              )}
            </span>
            {option.buyer_note && (
              <span className="text-[11.5px] leading-snug text-white/85">
                {option.buyer_note}
              </span>
            )}
          </button>
        )
      })}
      <p className="text-center text-[12px] text-black">
        Joining happens with your purchase — no separate step.
      </p>
      {error && (
        <p className="rounded-md bg-red-50 px-2 py-1 text-center text-[11px] text-red-700">
          {error}
        </p>
      )}
    </div>
  )
}
