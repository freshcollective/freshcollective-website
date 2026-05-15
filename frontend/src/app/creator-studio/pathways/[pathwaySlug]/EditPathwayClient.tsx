'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import type { CreatorPathway, CreatorStep } from '@/types/platform'
import { apiUrl } from '@/lib/api'

// ---------------------------------------------------------------------------
// Access / Pricing selector (same options as create form)
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
// Step content type label
// ---------------------------------------------------------------------------

const CONTENT_TYPE_LABEL: Record<string, string> = {
  text:       'Text',
  video:      'Video',
  audio:      'Audio',
  reflection: 'Reflection',
  exercise:   'Exercise',
}

// ---------------------------------------------------------------------------
// Add Step inline form
// ---------------------------------------------------------------------------

function AddStepForm({
  spaceSlug,
  pathwaySlug,
  onAdded,
  onCancel,
}: {
  spaceSlug: string
  pathwaySlug: string
  onAdded: () => void
  onCancel: () => void
}) {
  const [title, setTitle]           = useState('')
  const [contentType, setContentType] = useState('text')
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState<string | null>(null)

  async function handleAdd() {
    if (!title.trim()) { setError('Step title is required.'); return }
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathwaySlug}/steps`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ title: title.trim(), content_type: contentType }),
        },
      )
      if (!res.ok) {
        let detail: string | null = null
        try { const b = await res.json(); if (typeof b.detail === 'string') detail = b.detail } catch { /* ignore */ }
        setError(detail ?? 'Could not add step. Please try again.')
        return
      }
      onAdded()
    } catch {
      setError('Could not add step. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rounded-xl border border-teal-200 bg-teal-50/40 p-4">
      <p className="mb-3 text-[13px] font-semibold text-navy-900">New step</p>
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          type="text"
          value={title}
          autoFocus
          onChange={(e) => { setTitle(e.target.value); setError(null) }}
          placeholder="Step title"
          className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400"
        />
        <select
          value={contentType}
          onChange={(e) => setContentType(e.target.value)}
          className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
        >
          <option value="text">Text</option>
          <option value="video">Video</option>
          <option value="audio">Audio</option>
          <option value="reflection">Reflection</option>
          <option value="exercise">Exercise</option>
        </select>
      </div>
      {error && <p className="mt-2 text-[12px] text-red-600">{error}</p>}
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          disabled={loading || !title.trim()}
          onClick={handleAdd}
          className="rounded-lg px-4 py-1.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          {loading ? 'Adding…' : 'Add step'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="text-[13px] text-slate-500 transition-colors hover:text-navy-900"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main edit form
// ---------------------------------------------------------------------------

interface Props {
  pathway:   CreatorPathway
  steps:     CreatorStep[]
  spaceSlug: string
}

function centsToDisplay(cents: number | null): string {
  if (cents == null) return ''
  const dollars = cents / 100
  return Number.isInteger(dollars) ? `${dollars}` : dollars.toFixed(2)
}

export default function EditPathwayClient({ pathway, steps: initialSteps, spaceSlug }: Props) {
  const router = useRouter()
  const [, startTransition] = useTransition()

  const [title, setTitle]               = useState(pathway.title)
  const [description, setDescription]   = useState(pathway.description ?? '')
  const [practiceBody, setPracticeBody] = useState(pathway.practice_body ?? '')
  const [status, setStatus]             = useState<string>(pathway.status)
  const [accessType, setAccessType]     = useState<string>(pathway.access_type ?? 'free')
  const [priceDollars, setPriceDollars] = useState(centsToDisplay(pathway.price_cents))
  const [currency, setCurrency]         = useState(pathway.currency ?? 'AUD')
  const [loading, setLoading]           = useState(false)
  const [saved, setSaved]               = useState(false)
  const [error, setError]               = useState<string | null>(null)
  const [priceError, setPriceError]     = useState<string | null>(null)
  const [steps, setSteps]               = useState<CreatorStep[]>(initialSteps)
  const [addingStep, setAddingStep]     = useState(false)

  const isPaid = accessType === 'one_time' || accessType === 'subscription'

  function validate(): boolean {
    if (!title.trim()) { setError('Pathway title is required.'); return false }
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

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setPriceError(null)
    setSaved(false)
    if (!validate()) return

    const priceCents = isPaid ? Math.round(parseFloat(priceDollars) * 100) : null

    setLoading(true)
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}`),
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            title: title.trim(),
            description: description.trim() || null,
            practice_body: practiceBody.trim() || null,
            status,
            access_type: accessType,
            price_cents: priceCents,
            currency: isPaid ? currency : 'AUD',
            billing_interval: accessType === 'subscription' ? 'month' : null,
          }),
        },
      )

      if (!res.ok) {
        let detail: string | null = null
        try {
          const body = await res.json()
          if (typeof body.detail === 'string') detail = body.detail
        } catch { /* ignore */ }
        setError(detail ?? 'Could not save changes. Please try again.')
        return
      }

      setSaved(true)
      startTransition(() => { router.refresh() })
      setTimeout(() => setSaved(false), 3000)
    } catch {
      setError('Could not save changes. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  function handleStepAdded() {
    setAddingStep(false)
    startTransition(() => { router.refresh() })
    // Optimistically reload steps from server
    fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/pathways/${pathway.slug}/steps`), {
      credentials: 'include',
    })
      .then((r) => r.json())
      .then((data) => setSteps(data))
      .catch(() => { /* ignore, router.refresh() will handle */ })
  }

  return (
    <form onSubmit={handleSave} className="space-y-6">

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
          <option value="archived">Archived</option>
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

      {/* Global error / saved message */}
      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{error}</p>
      )}
      {saved && (
        <p className="rounded-lg px-3 py-2 text-[13px] font-medium" style={{ background: 'rgba(56,160,158,0.08)', color: '#38A09E' }}>
          Changes saved.
        </p>
      )}

      {/* Save button */}
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
          {loading ? 'Saving…' : 'Save changes'}
        </button>
      </div>

      {/* ── Pathway structure ── */}
      <div className="rounded-2xl border border-border bg-white p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-[16px] font-semibold text-navy-900">Pathway structure</h2>
            <p className="mt-0.5 text-[13px] text-slate-500">
              Add steps to shape the experience people will move through.
            </p>
          </div>
          <span className="text-[13px] text-slate-400">
            {steps.length} {steps.length === 1 ? 'step' : 'steps'}
          </span>
        </div>

        {/* Step list */}
        {steps.length > 0 && (
          <ul className="mb-4 space-y-2">
            {steps.map((step, i) => (
              <li
                key={step.id}
                className="flex items-center gap-3 rounded-lg border border-border bg-white px-4 py-3"
              >
                <span
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
                  style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E' }}
                >
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1 truncate text-[14px] font-medium text-navy-900">
                  {step.title}
                </span>
                <span
                  className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium"
                  style={{ background: 'rgba(0,0,0,0.05)', color: '#64748b' }}
                >
                  {CONTENT_TYPE_LABEL[step.content_type] ?? step.content_type}
                </span>
              </li>
            ))}
          </ul>
        )}

        {steps.length === 0 && !addingStep && (
          <p className="mb-4 text-[13px] italic text-slate-400">No steps yet.</p>
        )}

        {/* Add step */}
        {addingStep ? (
          <AddStepForm
            spaceSlug={spaceSlug}
            pathwaySlug={pathway.slug}
            onAdded={handleStepAdded}
            onCancel={() => setAddingStep(false)}
          />
        ) : (
          <button
            type="button"
            onClick={() => setAddingStep(true)}
            className="rounded-lg border border-dashed border-slate-300 px-4 py-2 text-[13px] font-medium text-slate-500 transition-colors hover:border-teal-300 hover:text-teal-700"
          >
            + Add step
          </button>
        )}
      </div>

    </form>
  )
}
