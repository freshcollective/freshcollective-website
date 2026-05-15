'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

// ---------------------------------------------------------------------------
// Access / Pricing selector
// ---------------------------------------------------------------------------

const ACCESS_OPTIONS = [
  {
    value: 'free',
    label: 'Free',
    description: 'Anyone with access to the collective can begin this pathway.',
  },
  {
    value: 'included',
    label: 'Included in collective access',
    description: 'Available to members who already have access to this collective.',
  },
  {
    value: 'one_time',
    label: 'One-off payment',
    description: 'People pay once to access this pathway.',
  },
  {
    value: 'subscription',
    label: 'Monthly subscription',
    description: 'People pay monthly for ongoing access to this pathway.',
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
  const isPaid = accessType === 'one_time' || accessType === 'subscription'

  return (
    <div>
      <label className="mb-2 block text-[12px] font-semibold text-slate-600">
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
                  <p className="mt-0.5 text-[12px] leading-relaxed text-slate-500">
                    {opt.description}
                  </p>
                </div>
              </div>
            </button>
          )
        })}
      </div>

      {/* Price fields for paid options */}
      {isPaid && (
        <div className="mt-3 flex gap-3">
          <div className="flex-1">
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">
              {accessType === 'subscription' ? 'Monthly price' : 'Price'}
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[14px] text-slate-400">
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
            <label className="mb-1 block text-[12px] font-semibold text-slate-600">Currency</label>
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

      {/* TODO: Connect pathway pricing to payment/checkout flow when Stripe is wired. */}
      {isPaid && (
        <p className="mt-2 text-[11px] text-slate-400">
          Pricing is saved for configuration. Payment processing will be connected when Stripe is set up.
        </p>
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

  const isPaid = accessType === 'one_time' || accessType === 'subscription'

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
        <label className="mb-1 block text-[12px] font-semibold text-slate-600">
          Pathway title <span className="font-normal text-slate-400">(required)</span>
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
        <label className="mb-1 block text-[12px] font-semibold text-slate-600">
          Short description{' '}
          <span className="font-normal text-slate-400">(optional)</span>
        </label>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="A guided pathway for moving slowly, reflecting honestly, and building new rhythm."
          className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
        />
      </div>

      {/* What will people practise? */}
      <div>
        <label className="mb-1 block text-[12px] font-semibold text-slate-600">
          What will people practise?{' '}
          <span className="font-normal text-slate-400">(optional)</span>
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
        <label className="mb-1 block text-[12px] font-semibold text-slate-600">Status</label>
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
          className="text-[14px] text-slate-500 transition-colors hover:text-navy-900"
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
