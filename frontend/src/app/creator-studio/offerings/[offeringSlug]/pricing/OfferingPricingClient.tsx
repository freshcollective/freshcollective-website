'use client'

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type {
  CreatorOffering, OfferingPricingKind, OfferingReadiness,
} from '@/types/platform'

interface Props {
  spaceSlug: string
  offering: CreatorOffering
  readiness: OfferingReadiness | null
}

/**
 * 💛 Pricing — two choices, and nothing else.
 *
 * Free, or a one-time purchase with a price. That is the whole surface,
 * and it is deliberately far simpler than the Pathway pricing screen: a
 * Pathway carries legacy access types and a relationship to central
 * Payment Options, where an Offering stores a **pricing intent** on its
 * own row (B4's ``pricing_kind`` / ``price_cents``).
 *
 * Nothing here creates a Payment Option, a Stripe session or a purchase
 * flow. Acquisition is Phase D; this screen records what the creator
 * decided so that phase has something to honour.
 *
 * Plan eligibility is enforced by the server
 * (``guard_paid_offers_enabled``). The UI reflects it rather than
 * deciding it — the radio is disabled and explained, and a creator who
 * reaches the endpoint another way is refused there too.
 */
export default function OfferingPricingClient({
  spaceSlug, offering, readiness,
}: Props) {
  const router = useRouter()
  const [kind, setKind] = useState<OfferingPricingKind | null>(offering.pricing_kind)
  const [dollars, setDollars] = useState(
    offering.price_cents != null ? (offering.price_cents / 100).toFixed(2) : '',
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  // The readiness checklist already knows whether this plan may charge;
  // reading it here avoids a second source of truth in the frontend.
  const planBlocked = (readiness?.requirements ?? []).find(
    (r) => r.id === 'plan_allows_pricing' && !r.met,
  )
  const paidAllowed = !planBlocked

  const base = apiUrl(`/api/creator/spaces/${spaceSlug}/offerings/${offering.slug}`)

  async function save(nextKind: OfferingPricingKind, nextDollars?: string) {
    setBusy(true)
    setError(null)
    setSaved(false)

    const payload: Record<string, unknown> = { pricing_kind: nextKind }
    if (nextKind === 'one_time') {
      const parsed = Number.parseFloat((nextDollars ?? dollars).replace(/[^0-9.]/g, ''))
      if (!Number.isFinite(parsed) || parsed <= 0) {
        setError('Set a price above zero.')
        setBusy(false)
        return
      }
      payload.price_cents = Math.round(parsed * 100)
    } else {
      payload.price_cents = null
    }

    try {
      const res = await fetch(base, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(
          typeof body.detail === 'string'
            ? body.detail
            : `That couldn't be saved (${res.status}).`,
        )
        return
      }
      setSaved(true)
      router.refresh()
    } catch {
      setError("That couldn't be saved. Please try again.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-[640px]">
      <div className="mb-6">
        <h2 className="text-[18px] font-semibold text-navy-900">Pricing</h2>
        <p className="mt-1 text-[14px] text-black">
          Decide whether this Offering is free or paid.
        </p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6">
        <fieldset>
          <legend className="sr-only">How is this Offering priced?</legend>

          <PricingOption
            id="pricing-free"
            checked={kind === 'free'}
            onChange={() => { setKind('free'); void save('free') }}
            disabled={busy}
            title="Free"
            body="Anyone in your Collective can download it at no cost."
          />

          <PricingOption
            id="pricing-one-time"
            checked={kind === 'one_time'}
            onChange={() => setKind('one_time')}
            disabled={busy || !paidAllowed}
            title="One-time purchase"
            body={
              paidAllowed
                ? 'People pay once and keep it — including any files you add or update later.'
                : planBlocked?.message
                  ?? "Your current plan doesn't include paid Offerings."
            }
          />
        </fieldset>

        {kind === 'one_time' && paidAllowed && (
          <div className="mt-5 border-t border-slate-100 pt-5">
            <label htmlFor="offering-price" className="block text-[14px] font-semibold text-navy-900">
              Price
            </label>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <div className="relative">
                <span
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[15px]"
                  style={{ color: 'rgba(12,24,38,0.5)' }}
                >
                  $
                </span>
                <input
                  id="offering-price"
                  inputMode="decimal"
                  value={dollars}
                  onChange={(e) => { setDollars(e.target.value); setSaved(false) }}
                  placeholder="0.00"
                  className="w-36 rounded-xl border border-slate-200 py-2.5 pl-7 pr-3 text-[15px] text-navy-900 outline-none focus:border-teal-400"
                />
              </div>
              <button
                type="button"
                onClick={() => save('one_time')}
                disabled={busy}
                className="rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                {busy ? 'Saving…' : 'Save price'}
              </button>
            </div>
            <p className="mt-2 text-[12.5px]" style={{ color: 'rgba(12,24,38,0.55)' }}>
              In your Collective&rsquo;s currency.
            </p>
          </div>
        )}

        {error && (
          <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-700">
            {error}
          </p>
        )}
        {saved && !error && (
          <p className="mt-4 text-[13px]" style={{ color: 'rgba(12,24,38,0.55)' }} aria-live="polite">
            Saved.
          </p>
        )}
      </div>

      {/* Honest about what has and has not been built. A creator setting
          a price today should not expect money to arrive tomorrow. */}
      <p className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-[13px] leading-relaxed text-black">
        Buying isn&rsquo;t switched on yet. Your choice here is saved and will
        be used when purchasing opens — nothing is charged to anyone in the
        meantime.
      </p>
    </div>
  )
}

function PricingOption({
  id, checked, onChange, disabled, title, body,
}: {
  id: string
  checked: boolean
  onChange: () => void
  disabled: boolean
  title: string
  body: string
}) {
  return (
    <label
      htmlFor={id}
      className="mt-3 flex cursor-pointer gap-3 rounded-xl border p-4 transition-colors first:mt-0"
      style={{
        borderColor: checked ? '#38A09E' : 'rgba(12,24,38,0.10)',
        background: checked ? 'rgba(56,160,158,0.05)' : 'white',
        opacity: disabled && !checked ? 0.6 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
    >
      <input
        id={id}
        type="radio"
        name="offering-pricing"
        checked={checked}
        onChange={onChange}
        disabled={disabled}
        className="mt-1 h-4 w-4 shrink-0 accent-teal-600"
      />
      <span>
        <span className="block text-[14.5px] font-semibold text-navy-900">{title}</span>
        <span className="mt-0.5 block text-[13px] leading-relaxed text-black">{body}</span>
      </span>
    </label>
  )
}
