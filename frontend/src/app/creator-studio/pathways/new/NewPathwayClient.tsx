'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

// ---------------------------------------------------------------------------
// Access / Pricing selector
// ---------------------------------------------------------------------------

/**
 * The four choices Pathway Settings can also maintain.
 *
 * "One-time purchase" is back (Stage 2A). Stage 0 removed it because
 * Pathway Settings treated a direct price as legacy and refused to
 * write one, so a creator could create a $49 Pathway and then be told
 * that is not how paid Pathways work. Offering a choice one surface
 * cannot maintain was the worse half of that inconsistency, so it was
 * the half that went. Settings can now maintain it, so it returns.
 *
 * **"Monthly subscription" is deliberately not here.** The column
 * still accepts ``access_type='subscription'`` and the row is
 * settable, but ``POST /api/checkout/pathway`` refuses anything but
 * ``one_time`` — so a subscription Pathway is unsellable by any door.
 * Ongoing member-paid access is configured through Payment Options.
 * Do not add it back without a checkout that can sell it.
 *
 * Simultaneous direct *and* Payment Option pricing on one Pathway is
 * Stage 2B, behind its own activation gate.
 */
const ACCESS_OPTIONS = [
  {
    value: 'free',
    label: 'Public',
    description: 'Anyone can find and preview this pathway. Members can begin it immediately.',
  },
  {
    value: 'included',
    label: 'Members only',
    description: 'Only signed-in members of this collective can see or begin this pathway.',
  },
  {
    value: 'one_time',
    label: 'One-time purchase',
    description: 'Members buy this Pathway on its own, for a single price you set here.',
  },
  {
    value: 'included_with_offer',
    label: 'Payment Option access',
    description: 'Only members whose Payment Option includes this pathway can access it. Set the price in Commerce \u2192 Payment Options.',
  },
]

function AccessPricingSection({
  accessType,
  setAccessType,
  priceDollars,
  setPriceDollars,
  currency,
  setCurrency,
  priceError,
}: {
  accessType: string
  setAccessType: (v: string) => void
  priceDollars: string
  setPriceDollars: (v: string) => void
  currency: string
  setCurrency: (v: string) => void
  priceError: string | null
}) {
  // `one_time` only. `subscription` is not offered in ACCESS_OPTIONS
  // and checkout refuses to sell it, so admitting it here would only
  // ever show a price box for an arrangement nobody can buy.
  const isPaid = accessType === 'one_time'

  return (
    <div>
      <label className="mb-2 block text-[12px] font-semibold text-black">
        Access and pricing
      </label>
      <div className="space-y-2">
        {ACCESS_OPTIONS.map((opt) => {
          const selected = accessType === opt.value
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => setAccessType(opt.value)}
              className="w-full rounded-xl border px-4 py-3 text-left transition-colors"
              style={
                selected
                  ? { borderColor: 'rgba(56,160,158,0.6)', background: 'rgba(56,160,158,0.05)' }
                  : { borderColor: '#e2e8f0', background: 'white' }
              }
            >
              <div className="flex items-center gap-3">
                <div
                  className="mt-0.5 h-4 w-4 shrink-0 rounded-full border-2 transition-colors"
                  style={
                    selected
                      ? { borderColor: '#38A09E', background: '#38A09E' }
                      : { borderColor: '#cbd5e1', background: 'white' }
                  }
                />
                <div>
                  <p className="text-[14px] font-semibold text-navy-900">{opt.label}</p>
                  <p className="mt-0.5 text-[12px] leading-relaxed text-black">
                    {opt.description}
                  </p>
                </div>
              </div>
            </button>
          )
        })}
      </div>

      {/* Price fields — live again as of Stage 2A, for `one_time`.
          The currency select is editable *here only*: this is the one
          moment it can be chosen, because once the Pathway has a price
          `update_pathway` refuses to change it (purchases are recorded
          in it, and re-denominating would misstate a creator's own
          earnings). Pathway Settings shows it read-only. */}
      {isPaid && (
        <div className="mt-3 flex gap-3">
          <div className="flex-1">
            <label className="mb-1 block text-[12px] font-semibold text-black">
              Price
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[14px] text-black">
                $
              </span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={priceDollars}
                onChange={(e) => setPriceDollars(e.target.value)}
                placeholder="0.00"
                className={`w-full rounded-lg border py-2 pl-7 pr-3 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400 ${
                  priceError ? 'border-red-300' : 'border-slate-200'
                }`}
              />
            </div>
            {priceError && (
              <p className="mt-1 text-[12px] text-red-600">{priceError}</p>
            )}
          </div>
          <div className="w-28">
            <label className="mb-1 block text-[12px] font-semibold text-black">Currency</label>
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
            >
              <option value="AUD">AUD</option>
              <option value="USD">USD</option>
              <option value="GBP">GBP</option>
              <option value="EUR">EUR</option>
              <option value="NZD">NZD</option>
            </select>
          </div>
        </div>
      )}

      {isPaid && (
        <p className="mt-2 text-[11px] text-black">
          Members pay this once for lifetime access to this Pathway. You
          can change the amount later in the Pathway&rsquo;s settings;
          the currency is fixed once set.
        </p>
      )}

      {accessType === 'included_with_offer' && (
        <div
          className="mt-3 rounded-xl px-4 py-3 text-[12px] leading-relaxed text-black"
          style={{ background: 'rgba(56,160,158,0.05)', border: '1px solid rgba(56,160,158,0.20)' }}
        >
          <p className="font-semibold text-navy-900">How paid access works</p>
          <p className="mt-1">
            <strong>Payment Options</strong> are how you charge for a Pathway.
            One Option can cover several experiences, and can offer a single
            payment or a payment plan \u2014 so it handles bundles and
            instalments as well as a straightforward purchase.
          </p>
          <p className="mt-1">
            Create the Pathway first, then add it to an Option in
            Commerce \u2192 Payment Options.
          </p>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main form
// ---------------------------------------------------------------------------

export default function NewPathwayClient({ spaceSlug }: { spaceSlug: string }) {
  const router = useRouter()
  const [title, setTitle]               = useState('')
  const [description, setDescription]   = useState('')
  const [practiceBody, setPracticeBody] = useState('')
  const [status, setStatus]             = useState('draft')
  const [accessType, setAccessType]     = useState('free')
  const [priceDollars, setPriceDollars] = useState('')
  const [currency, setCurrency]         = useState('AUD')
  const [loading, setLoading]           = useState(false)
  const [error, setError]               = useState<string | null>(null)
  const [priceError, setPriceError]     = useState<string | null>(null)

  // `one_time` only. `subscription` is not offered in ACCESS_OPTIONS
  // and checkout refuses to sell it, so admitting it here would only
  // ever show a price box for an arrangement nobody can buy.
  const isPaid = accessType === 'one_time'

  function validate(): boolean {
    if (!title.trim()) {
      setError('Pathway title is required.')
      return false
    }
    if (isPaid) {
      const dollars = parseFloat(priceDollars)
      if (!priceDollars.trim() || isNaN(dollars)) {
        setPriceError('Enter a price for this paid pathway.')
        return false
      }
      if (dollars <= 0) {
        setPriceError('Price must be greater than 0.')
        return false
      }
    }
    return true
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setPriceError(null)
    if (!validate()) return

    const priceCents = isPaid ? Math.round(parseFloat(priceDollars) * 100) : null

    setLoading(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/pathways`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim() || null,
          practice_body: practiceBody.trim() || null,
          status,
          access_type: accessType,
          price_cents: priceCents,
          currency: isPaid ? currency : null,
          billing_interval: accessType === 'subscription' ? 'month' : null,
        }),
      })

      if (!res.ok) {
        let detail: string | null = null
        try {
          const body = await res.json()
          if (typeof body.detail === 'string') detail = body.detail
        } catch { /* ignore */ }
        setError(detail ?? 'Could not create pathway. Please try again.')
        return
      }

      const created = await res.json()
      router.push(`/creator-studio/pathways/${created.slug}`)
    } catch {
      setError('Could not create pathway. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">

      {/* Title */}
      <div>
        <label className="mb-1 block text-[12px] font-semibold text-black">
          Pathway title <span className="font-normal text-black">(required)</span>
        </label>
        <input
          type="text"
          value={title}
          onChange={(e) => { setTitle(e.target.value); setError(null) }}
          placeholder="e.g. Slow Growth Practice"
          className={`w-full rounded-lg border px-3 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400 ${
            error && !title.trim() ? 'border-red-300' : 'border-slate-200'
          }`}
        />
      </div>

      {/* Short description */}
      <div>
        <label className="mb-1 block text-[12px] font-semibold text-black">
          Short description{' '}
          <span className="font-normal text-black">(optional)</span>
        </label>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="A guided pathway for moving slowly, reflecting honestly, and building new rhythm."
          className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
        />
      </div>

      {/* What will people practice? */}
      <div>
        <label className="mb-1 block text-[12px] font-semibold text-black">
          What will people practice?{' '}
          <span className="font-normal text-black">(optional)</span>
        </label>
        <textarea
          value={practiceBody}
          onChange={(e) => setPracticeBody(e.target.value)}
          placeholder="Describe the shift, skill, rhythm, or experience this pathway supports."
          rows={4}
          className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
        />
      </div>

      {/* Status */}
      <div>
        <label className="mb-1 block text-[12px] font-semibold text-black">Status</label>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
        >
          <option value="draft">Draft</option>
          <option value="active">Published</option>
          <option value="coming_soon">Coming soon</option>
        </select>
      </div>

      {/* Conversations — managed in one place now. */}
      <div
        className="rounded-xl px-4 py-3"
        style={{ background: 'rgba(56,160,158,0.05)', border: '1px solid rgba(56,160,158,0.20)' }}
      >
        <p className="text-[13.5px] font-semibold text-navy-900">
          Want to connect this experience to a conversation?
        </p>
        <p className="mt-0.5 text-[12px] leading-relaxed text-black">
          Manage your channels in Conversations. One channel can be linked to
          several Pathways, Gatherings and Series, so an ongoing conversation
          can carry across them.
        </p>
        <Link
          href="/creator-studio/community/channels"
          className="mt-2 inline-block text-[12.5px] font-semibold text-teal-700 underline decoration-teal-300 underline-offset-2 hover:text-teal-800"
        >
          Manage Channels
        </Link>
      </div>

      {/* Access and pricing */}
      <AccessPricingSection
        accessType={accessType}
        setAccessType={(v) => { setAccessType(v); setPriceError(null) }}
        priceDollars={priceDollars}
        setPriceDollars={(v) => { setPriceDollars(v); setPriceError(null) }}
        currency={currency}
        setCurrency={setCurrency}
        priceError={priceError}
      />

      {/* Global error */}
      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{error}</p>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between border-t border-border pt-5">
        <button
          type="button"
          onClick={() => router.push('/creator-studio/pathways')}
          className="text-[14px] text-black transition-colors hover:text-navy-900"
        >
          ← Back to Pathways
        </button>
        <button
          type="submit"
          disabled={loading || !title.trim()}
          className="rounded-xl px-6 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          {loading ? 'Creating…' : 'Create pathway'}
        </button>
      </div>

    </form>
  )
}
