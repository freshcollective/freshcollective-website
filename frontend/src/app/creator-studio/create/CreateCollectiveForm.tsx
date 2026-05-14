'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

const CATEGORIES = [
  'Intentional living',
  'Leadership',
  'Creativity',
  'Wellbeing',
  'Embodiment',
  'Learning',
  'Other',
]

function CheckIcon() {
  return (
    <svg width="22" height="16" viewBox="0 0 22 16" fill="none" aria-hidden="true">
      <path
        d="M2 7.5l6 6L20 2"
        stroke="#38A09E"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function SuccessState({ name }: { name: string }) {
  return (
    <div
      className="flex min-h-[70vh] flex-col items-center justify-center px-8 py-16 text-center"
      style={{ background: '#F7F8FA' }}
    >
      <div
        className="mb-6 flex h-14 w-14 items-center justify-center rounded-full"
        style={{
          background: 'rgba(56,160,158,0.12)',
          border: '1.5px solid rgba(56,160,158,0.38)',
        }}
      >
        <CheckIcon />
      </div>
      <h2 className="mb-3 font-serif text-2xl text-navy-900 md:text-3xl">
        Your collective foundation is started.
      </h2>
      {name && (
        <p className="mb-2 text-[13px] font-medium text-teal-600">
          &ldquo;{name}&rdquo; is saved as a draft.
        </p>
      )}
      <p className="mb-8 max-w-[420px] text-[14px] leading-relaxed text-slate-400">
        Next, shape the first pathway, gathering, and resources that will hold the experience.
      </p>
      <div className="flex flex-col gap-3 sm:flex-row">
        <Link
          href="/creator-studio/setup"
          className="rounded-xl px-7 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          Continue setup
        </Link>
        <Link
          href="/creator-studio"
          className="rounded-xl border border-slate-200 bg-white px-7 py-3 text-[14px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
        >
          Go to Creator Studio
        </Link>
      </div>
    </div>
  )
}

export default function CreateCollectiveForm() {
  const router = useRouter()

  const [name, setName] = useState('')
  const [tagline, setTagline] = useState('')
  const [whoFor, setWhoFor] = useState('')
  const [whatChange, setWhatChange] = useState('')
  const [category, setCategory] = useState('')
  const [startAs, setStartAs] = useState<'draft' | 'publish_later'>('draft')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) {
      setError('Please enter a name for your collective.')
      document.getElementById('collective-name')?.focus()
      return
    }

    setSaving(true)
    setError(null)

    try {
      const description =
        [
          whoFor.trim() && `Who this is for: ${whoFor.trim()}`,
          whatChange.trim() && `What people practise: ${whatChange.trim()}`,
        ]
          .filter(Boolean)
          .join('\n\n') || null

      const res = await fetch(apiUrl('/api/creator/spaces'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          name: name.trim(),
          tagline: tagline.trim() || null,
          description,
          // Note: `category` and `startAs` are not yet persisted — the Space model
          // does not have category/visibility fields beyond is_public.
          // TODO: add category to Space model and pass it here when available.
          // All new collectives are created as private drafts (is_public: false, status: 'draft').
        }),
      })

      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try {
          const b = await res.json()
          detail = typeof b.detail === 'string' ? b.detail : detail
        } catch {}
        throw new Error(detail)
      }

      setSuccess(true)
      router.refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  if (success) return <SuccessState name={name} />

  return (
    <div className="min-h-screen" style={{ background: '#F7F8FA' }}>
      <div className="mx-auto max-w-2xl px-6 py-12">

        {/* Page header */}
        <div className="mb-8">
          <p
            className="mb-2 text-[10.5px] font-bold uppercase tracking-[0.20em]"
            style={{ color: '#38A09E' }}
          >
            Create your collective
          </p>
          <h1 className="mb-2 font-serif text-2xl text-navy-900 md:text-3xl">
            Start with the foundation.
          </h1>
          <p className="text-[14px] leading-relaxed text-slate-400">
            Give your collective enough shape to begin. You can refine everything later.
          </p>
        </div>

        {/* Calm note */}
        <div
          className="mb-8 rounded-xl px-5 py-4"
          style={{
            background: 'rgba(56,160,158,0.06)',
            border: '1px solid rgba(56,160,158,0.16)',
          }}
        >
          <p className="mb-1 text-[13px] font-semibold" style={{ color: '#2d8a88' }}>
            Your first collective starts as a draft.
          </p>
          <p className="text-[12.5px] leading-relaxed" style={{ color: '#4a9e9c' }}>
            You can add pathways, gatherings, resources, and community once the foundation is in place.
          </p>
        </div>

        {/* Form card */}
        <div
          className="rounded-2xl bg-white px-8 py-8"
          style={{
            border: '1px solid rgba(0,0,0,0.07)',
            boxShadow: '0 2px 16px rgba(0,0,0,0.05)',
          }}
        >
          <form onSubmit={handleSubmit} className="space-y-6">

            {/* 1. Collective name */}
            <div>
              <label
                htmlFor="collective-name"
                className="mb-1.5 block text-[13px] font-semibold text-navy-900"
              >
                Collective name{' '}
                <span aria-hidden="true" style={{ color: '#38A09E' }}>*</span>
              </label>
              <input
                id="collective-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Living Intentionally"
                maxLength={200}
                className="w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-300 transition-colors focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
              />
            </div>

            {/* 2. Short tagline */}
            <div>
              <label
                htmlFor="collective-tagline"
                className="mb-1.5 block text-[13px] font-semibold text-navy-900"
              >
                Short tagline
              </label>
              <input
                id="collective-tagline"
                type="text"
                value={tagline}
                onChange={(e) => setTagline(e.target.value)}
                placeholder="A guided collective for people ready to live with more clarity."
                maxLength={300}
                className="w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-300 transition-colors focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
              />
            </div>

            {/* 3. Who is this for */}
            <div>
              <label
                htmlFor="collective-who"
                className="mb-1.5 block text-[13px] font-semibold text-navy-900"
              >
                Who is this for?
              </label>
              <textarea
                id="collective-who"
                value={whoFor}
                onChange={(e) => setWhoFor(e.target.value)}
                placeholder="Describe the people this collective is designed for."
                rows={2}
                className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-300 transition-colors focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
              />
            </div>

            {/* 4. What change */}
            <div>
              <label
                htmlFor="collective-change"
                className="mb-1.5 block text-[13px] font-semibold text-navy-900"
              >
                What change does this collective help people practise?
              </label>
              <textarea
                id="collective-change"
                value={whatChange}
                onChange={(e) => setWhatChange(e.target.value)}
                placeholder="What will people begin to see, feel, practise, or live differently?"
                rows={2}
                className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-300 transition-colors focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
              />
            </div>

            {/* 5. Category */}
            <div>
              <p className="mb-2 text-[13px] font-semibold text-navy-900">Category</p>
              <div className="flex flex-wrap gap-1.5">
                {CATEGORIES.map((cat) => (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => setCategory(cat === category ? '' : cat)}
                    className="rounded-full border px-3 py-1 text-[12.5px] font-medium transition-all"
                    style={{
                      borderColor: category === cat ? '#38A09E' : '#e2e8f0',
                      background: category === cat ? 'rgba(56,160,158,0.08)' : 'transparent',
                      color: category === cat ? '#2d8a88' : '#94a3b8',
                    }}
                  >
                    {cat}
                  </button>
                ))}
              </div>
              {/* TODO: persist category when Space model supports a category field */}
            </div>

            {/* 6. Start as */}
            <div>
              <p className="mb-2 text-[13px] font-semibold text-navy-900">Start as</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {(
                  [
                    {
                      value: 'draft' as const,
                      label: 'Draft',
                      desc: 'Private while you build.',
                    },
                    {
                      value: 'publish_later' as const,
                      label: 'Publish when ready',
                      desc: 'Open it when it is ready to hold people.',
                    },
                  ] as const
                ).map((opt) => (
                  <label
                    key={opt.value}
                    className="flex cursor-pointer items-start gap-3 rounded-lg border p-3.5 transition-all"
                    style={{
                      borderColor: startAs === opt.value ? 'rgba(56,160,158,0.36)' : '#e2e8f0',
                      background: startAs === opt.value ? 'rgba(56,160,158,0.05)' : 'transparent',
                    }}
                  >
                    <input
                      type="radio"
                      name="start-as"
                      value={opt.value}
                      checked={startAs === opt.value}
                      onChange={() => setStartAs(opt.value)}
                      className="mt-0.5 accent-teal-500"
                    />
                    <div>
                      <p className="text-[13px] font-medium text-navy-900">{opt.label}</p>
                      <p className="mt-0.5 text-[12px] text-slate-400">{opt.desc}</p>
                    </div>
                  </label>
                ))}
              </div>
              <p className="mt-2 text-[11.5px] text-slate-300">
                All new collectives are created as private drafts.
              </p>
            </div>

            {/* Error */}
            {error && (
              <p
                className="rounded-lg px-4 py-3 text-[13px]"
                style={{
                  background: 'rgba(239,68,68,0.06)',
                  color: '#dc2626',
                  border: '1px solid rgba(239,68,68,0.18)',
                }}
              >
                {error}
              </p>
            )}

            {/* Actions */}
            <div className="flex items-center gap-5 pt-1">
              <button
                type="submit"
                disabled={saving}
                className="inline-flex items-center rounded-xl px-6 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
                style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
              >
                {saving ? 'Creating…' : 'Create collective'}
              </button>
              <Link
                href="/creator-studio"
                className="text-[13px] text-slate-400 transition-colors hover:text-slate-600"
              >
                Back to Creator Studio
              </Link>
            </div>

          </form>
        </div>

      </div>
    </div>
  )
}
