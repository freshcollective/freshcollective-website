'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import { MAX_COLLECTIVES_FOR_FOUNDING_CREATOR } from '@/lib/creatorPlan'

const CATEGORIES = [
  'Intentional living',
  'Leadership',
  'Creativity',
  'Wellbeing',
  'Embodiment',
  'Learning',
  'Other',
]

// ---------------------------------------------------------------------------
// Live preview panel — receives live form values as props
// ---------------------------------------------------------------------------

interface PreviewPanelProps {
  name: string
  tagline: string
  category: string
}

function PreviewPanel({ name, tagline, category }: PreviewPanelProps) {
  const displayName = name.trim() || 'Your Collective'
  const displayTagline = tagline.trim() || 'A guided collective for meaningful change.'
  const hasName = name.trim().length > 0

  return (
    <div
      className="relative overflow-hidden rounded-3xl px-7 py-8"
      style={{
        background: 'linear-gradient(145deg, #071824 0%, #0A2C2B 65%, #071F1E 100%)',
        border: '1px solid rgba(56,160,158,0.16)',
        boxShadow:
          '0 8px 48px rgba(0,0,0,0.24), inset 0 1px 0 rgba(255,255,255,0.04)',
      }}
    >
      {/* Atmospheric teal glow */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
        style={{
          background:
            'radial-gradient(ellipse 80% 55% at 20% 20%, rgba(56,160,158,0.20) 0%, transparent 60%)',
        }}
      />

      <div className="relative z-10 flex flex-col">

        {/* Panel label with live indicator */}
        <div className="mb-5 flex items-center gap-2">
          <div
            className="h-1.5 w-1.5 rounded-full transition-colors duration-500"
            style={{ background: hasName ? '#55B8B6' : 'rgba(255,255,255,0.18)' }}
          />
          <p
            className="text-[9.5px] font-bold uppercase tracking-[0.22em]"
            style={{ color: 'rgba(255,255,255,0.26)' }}
          >
            Live preview
          </p>
        </div>

        {/* Panel heading */}
        <p className="mb-1.5 font-serif text-[18px] leading-snug text-white">
          Your collective is taking shape.
        </p>
        <p
          className="mb-7 text-[12.5px] leading-relaxed"
          style={{ color: 'rgba(255,255,255,0.38)' }}
        >
          As you add the foundation, this preview becomes the first outline of the
          experience you are building.
        </p>

        {/* Preview card */}
        <div
          className="rounded-2xl px-5 py-5"
          style={{
            background: 'rgba(255,255,255,0.05)',
            border: '1px solid rgba(255,255,255,0.08)',
          }}
        >
          {/* Name + Draft badge */}
          <div className="mb-2 flex items-start justify-between gap-3">
            <span
              className="font-serif text-[15px] leading-snug text-white transition-opacity duration-300"
              style={{ opacity: hasName ? 1 : 0.40 }}
            >
              {displayName}
            </span>
            <span
              className="mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide"
              style={{ background: 'rgba(56,160,158,0.22)', color: '#55B8B6' }}
            >
              Draft
            </span>
          </div>

          {/* Tagline */}
          <p
            className="mb-4 text-[11.5px] leading-relaxed transition-opacity duration-300"
            style={{
              color: 'rgba(255,255,255,0.36)',
              opacity: tagline.trim() ? 1 : 0.55,
            }}
          >
            {displayTagline}
          </p>

          {/* Category badge if selected */}
          {category && (
            <div className="mb-3">
              <span
                className="rounded-full px-2.5 py-0.5 text-[10px] font-semibold"
                style={{
                  background: 'rgba(56,160,158,0.16)',
                  color: '#55B8B6',
                }}
              >
                {category}
              </span>
            </div>
          )}

          {/* Preview rows */}
          {(['Pathways', 'Live gatherings', 'Resources'] as const).map((label) => (
            <div
              key={label}
              className="flex items-center gap-2.5 py-2.5"
              style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}
            >
              <div
                className="h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ background: 'rgba(56,160,158,0.38)' }}
              />
              <span
                className="flex-1 text-[11.5px]"
                style={{ color: 'rgba(255,255,255,0.30)' }}
              >
                {label}
              </span>
              <span
                className="text-[10px]"
                style={{ color: 'rgba(255,255,255,0.14)' }}
              >
                Not yet added
              </span>
            </div>
          ))}
        </div>

        {/* Divider + note */}
        <div
          className="mt-6 pt-6"
          style={{ borderTop: '1px solid rgba(255,255,255,0.07)' }}
        >
          <p
            className="mb-1.5 text-[12.5px] font-semibold"
            style={{ color: 'rgba(255,255,255,0.65)' }}
          >
            Start private. Shape it slowly.
          </p>
          <p
            className="text-[12px] leading-relaxed"
            style={{ color: 'rgba(255,255,255,0.30)' }}
          >
            Add the foundation first. Then build the pathways, gatherings, resources,
            and community around it.
          </p>
        </div>

        <p className="mt-6 text-[11px]" style={{ color: 'rgba(255,255,255,0.16)' }}>
          You can build this one step at a time.
        </p>

      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Success state
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Limit reached state
// ---------------------------------------------------------------------------

function LimitReached() {
  return (
    <div
      className="flex min-h-[70vh] flex-col items-center justify-center px-8 py-16 text-center"
      style={{ background: '#F7F8FA' }}
    >
      <div
        className="mb-6 flex h-14 w-14 items-center justify-center rounded-full"
        style={{
          background: 'rgba(0,0,0,0.05)',
          border: '1.5px solid rgba(0,0,0,0.10)',
        }}
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <circle cx="10" cy="10" r="8.5" stroke="#94a3b8" strokeWidth="1.5" />
          <path d="M10 6v4.5" stroke="#94a3b8" strokeWidth="1.5" strokeLinecap="round" />
          <circle cx="10" cy="13.5" r="0.75" fill="#94a3b8" />
        </svg>
      </div>
      <h2 className="mb-3 font-serif text-2xl text-navy-900">
        You have used your {MAX_COLLECTIVES_FOR_FOUNDING_CREATOR} included collectives.
      </h2>
      <p className="mb-8 max-w-[400px] text-[14px] leading-relaxed text-slate-400">
        Founding Creator access includes up to {MAX_COLLECTIVES_FOR_FOUNDING_CREATOR} collectives.
        Creator Plus for additional collectives is coming soon.
      </p>
      <Link
        href="/creator-studio"
        className="rounded-xl border border-slate-200 bg-white px-7 py-3 text-[14px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
      >
        Back to Creator Studio
      </Link>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function CreateCollectiveForm({ existingCount }: { existingCount: number }) {
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

  if (existingCount >= MAX_COLLECTIVES_FOR_FOUNDING_CREATOR) return <LimitReached />
  if (success) return <SuccessState name={name} />

  return (
    <div
      className="relative min-h-screen"
      style={{
        background: 'linear-gradient(160deg, #EEF3F2 0%, #F7F8FA 50%, #F2F6F5 100%)',
      }}
    >
      {/* Faint teal glow — contained in the content column */}
      <div
        className="pointer-events-none absolute right-0 top-0 h-[640px] w-[640px] translate-x-[38%] -translate-y-[15%] rounded-full"
        aria-hidden="true"
        style={{
          background:
            'radial-gradient(circle, rgba(56,160,158,0.09) 0%, transparent 65%)',
        }}
      />

      <div className="relative mx-auto max-w-5xl px-6 py-10">

        {/* Page header */}
        <div className="mb-8">
          <p
            className="mb-2 text-[10px] font-bold uppercase tracking-[0.22em]"
            style={{ color: '#38A09E' }}
          >
            Create your collective
          </p>
          <h1 className="mb-1.5 font-serif text-[1.75rem] leading-tight text-navy-900">
            Start with the foundation.
          </h1>
          <p className="text-[13.5px] leading-relaxed text-slate-400">
            Give your collective enough shape to begin. You can refine everything later.
          </p>
          <p className="mt-2 text-[12px] text-slate-400">
            Founding Creator access includes up to {MAX_COLLECTIVES_FOR_FOUNDING_CREATOR} collectives.
          </p>
        </div>

        {/* Two-column grid — form left, preview right */}
        <div className="grid items-start gap-6 lg:grid-cols-[1fr,370px]">

          {/* ── LEFT: form card ── */}
          <div
            className="rounded-3xl bg-white"
            style={{
              border: '1px solid rgba(56,160,158,0.14)',
              boxShadow:
                '0 8px 40px rgba(0,0,0,0.08), inset 0 1px 0 rgba(255,255,255,0.80)',
            }}
          >

            {/* Card header */}
            <div
              className="flex items-start justify-between gap-4 px-8 pb-6 pt-8"
              style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}
            >
              <div>
                <p className="mb-1 font-serif text-[16.5px] text-navy-900">
                  Collective foundation
                </p>
                <p className="text-[12.5px] leading-relaxed text-slate-400">
                  Start with the essentials. These details help people understand what
                  your collective is for.
                </p>
              </div>
              <span
                className="mt-0.5 shrink-0 rounded-full px-2.5 py-1 text-[10px] font-semibold"
                style={{
                  background: 'rgba(56,160,158,0.08)',
                  color: '#38A09E',
                }}
              >
                Step 1 of 4
              </span>
            </div>

            {/* Form body */}
            <form onSubmit={handleSubmit} className="px-8 py-8">

              {/* ── Section 1: Name the work ── */}
              <div className="mb-7">
                <p
                  className="mb-4 text-[10px] font-bold uppercase tracking-[0.16em]"
                  style={{ color: '#b0bec5' }}
                >
                  Name the work
                </p>
                <div className="space-y-5">
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
                      className="w-full rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-300 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
                    />
                  </div>
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
                      className="w-full rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-300 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
                    />
                  </div>
                </div>
              </div>

              <div className="mb-7 border-t" style={{ borderColor: 'rgba(0,0,0,0.05)' }} />

              {/* ── Section 2: Define the people and change ── */}
              <div className="mb-7">
                <p
                  className="mb-4 text-[10px] font-bold uppercase tracking-[0.16em]"
                  style={{ color: '#b0bec5' }}
                >
                  Define the people and change
                </p>
                <div className="space-y-5">
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
                      className="w-full resize-none rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-300 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
                    />
                  </div>
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
                      className="w-full resize-none rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-300 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
                    />
                  </div>
                </div>
              </div>

              <div className="mb-7 border-t" style={{ borderColor: 'rgba(0,0,0,0.05)' }} />

              {/* ── Section 3: Set the starting point ── */}
              <div className="mb-6">
                <p
                  className="mb-4 text-[10px] font-bold uppercase tracking-[0.16em]"
                  style={{ color: '#b0bec5' }}
                >
                  Set the starting point
                </p>

                {/* Category */}
                <div className="mb-6">
                  <p className="mb-2.5 text-[13px] font-semibold text-navy-900">Category</p>
                  <div className="flex flex-wrap gap-1.5">
                    {CATEGORIES.map((cat) => (
                      <button
                        key={cat}
                        type="button"
                        onClick={() => setCategory(cat === category ? '' : cat)}
                        className="rounded-full border px-3 py-1 text-[12px] font-medium transition-all hover:border-teal-300 hover:text-teal-600"
                        style={{
                          borderColor: category === cat ? '#38A09E' : '#e2e8f0',
                          background:
                            category === cat ? 'rgba(56,160,158,0.10)' : 'transparent',
                          color: category === cat ? '#2d8a88' : '#94a3b8',
                        }}
                      >
                        {cat}
                      </button>
                    ))}
                  </div>
                  {/* TODO: persist category when Space model supports a category field */}
                </div>

                {/* Start as */}
                <div>
                  <p className="mb-2.5 text-[13px] font-semibold text-navy-900">Start as</p>
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
                        className="flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-all"
                        style={{
                          borderColor:
                            startAs === opt.value ? 'rgba(56,160,158,0.40)' : '#e2e8f0',
                          background:
                            startAs === opt.value ? 'rgba(56,160,158,0.06)' : 'transparent',
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
              </div>

              {/* Error */}
              {error && (
                <div
                  className="mb-5 rounded-xl px-4 py-3 text-[13px]"
                  style={{
                    background: 'rgba(239,68,68,0.06)',
                    color: '#dc2626',
                    border: '1px solid rgba(239,68,68,0.18)',
                  }}
                >
                  {error}
                </div>
              )}

              {/* Actions */}
              <div className="flex items-center gap-5">
                <button
                  type="submit"
                  disabled={saving}
                  className="inline-flex items-center rounded-xl px-7 py-2.5 text-[14px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90 disabled:translate-y-0 disabled:opacity-60"
                  style={{
                    background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                    boxShadow: '0 3px 18px rgba(56,160,158,0.36)',
                  }}
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

          {/* ── RIGHT: live preview panel ── */}
          <div className="lg:sticky lg:top-8">
            <PreviewPanel name={name} tagline={tagline} category={category} />
          </div>

        </div>
      </div>
    </div>
  )
}
