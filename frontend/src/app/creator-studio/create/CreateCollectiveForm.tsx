'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CATEGORIES = [
  'Intentional living',
  'Leadership',
  'Creativity',
  'Wellbeing',
  'Embodiment',
  'Learning',
  'Other',
]

const EXAMPLE_COLLECTIVES = [
  {
    title: 'Living Intentionally',
    tagline: 'A collective for slowing down, reconnecting, and building a life that actually fits.',
    category: 'Intentional living',
    members: 24,
  },
  {
    title: 'Creative Practice',
    tagline: 'For makers, writers, artists, and creators building sustainable creative rhythm.',
    category: 'Creativity',
    members: 18,
  },
  {
    title: 'Embodied Leadership',
    tagline: 'Exploring new ways of leading with presence, clarity, and self-trust.',
    category: 'Leadership',
    members: 31,
  },
]

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CollectiveCard({
  collective,
  featured,
}: {
  collective: (typeof EXAMPLE_COLLECTIVES)[0]
  featured?: boolean
}) {
  return (
    <div
      className="flex h-full min-h-[220px] flex-col rounded-2xl p-6"
      style={{
        background: featured
          ? 'linear-gradient(145deg, #073B3A 0%, #062F35 100%)'
          : 'linear-gradient(145deg, #071824 0%, #0C2030 100%)',
        border: `1px solid ${featured ? 'rgba(56,160,158,0.28)' : 'rgba(255,255,255,0.07)'}`,
        boxShadow: featured
          ? '0 24px 64px rgba(0,0,0,0.55), 0 0 0 1px rgba(56,160,158,0.10)'
          : '0 8px 28px rgba(0,0,0,0.35)',
      }}
    >
      <div className="mb-4 flex items-center justify-between gap-2">
        <span
          className="rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide"
          style={{ background: 'rgba(56,160,158,0.18)', color: '#55B8B6' }}
        >
          {collective.category}
        </span>
        <span className="text-[11px]" style={{ color: 'rgba(255,255,255,0.32)' }}>
          {collective.members} members
        </span>
      </div>
      <p className="mb-2 font-serif text-[17px] leading-snug text-white">
        {collective.title}
      </p>
      <p
        className="flex-1 text-[12.5px] leading-relaxed"
        style={{ color: 'rgba(255,255,255,0.50)' }}
      >
        {collective.tagline}
      </p>
      <div className="mt-5 flex items-center gap-1.5">
        <div className="h-1.5 w-1.5 rounded-full" style={{ background: '#42C7C6' }} aria-hidden="true" />
        <span className="text-[11px] font-medium" style={{ color: 'rgba(255,255,255,0.40)' }}>
          Active
        </span>
      </div>
    </div>
  )
}

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
// Main component
// ---------------------------------------------------------------------------

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

  function scrollToForm() {
    document.getElementById('create-form')?.scrollIntoView({ behavior: 'smooth' })
  }

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
    <div>

      {/* ── Section 1: Hero ──────────────────────────────────────────────── */}
      <section
        className="relative overflow-hidden"
        style={{ background: '#071824', minHeight: 'clamp(420px, 52vh, 580px)' }}
      >
        {/* Atmospheric teal glow */}
        <div
          className="pointer-events-none absolute inset-0"
          aria-hidden="true"
          style={{
            background:
              'radial-gradient(ellipse 70% 60% at 40% 30%, rgba(38,110,108,0.18) 0%, transparent 65%)',
          }}
        />
        {/* Grain */}
        <div
          className="pointer-events-none absolute inset-0"
          aria-hidden="true"
          style={{
            backgroundImage: `url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='300' height='300' filter='url(%23n)' opacity='0.024'/></svg>")`,
          }}
        />

        <div className="relative z-10 flex h-full flex-col items-center justify-center px-6 py-16 text-center md:py-20">
          <p
            className="mb-5 text-[10.5px] font-bold uppercase tracking-[0.22em]"
            style={{ color: 'rgba(255,255,255,0.30)' }}
          >
            Create your collective
          </p>

          <h1
            className="mb-6 max-w-2xl"
            style={{
              fontSize: 'clamp(2.2rem, 4.8vw, 4rem)',
              lineHeight: '1.06',
              letterSpacing: '-0.03em',
              fontWeight: 660,
            }}
          >
            <span className="block text-white">Build the collective</span>
            <span
              className="block"
              style={{
                backgroundImage:
                  'linear-gradient(100deg, #42C7C6 0%, #7FDAD9 28%, #D8F5F2 55%, #FFFFFF 78%)',
                WebkitBackgroundClip: 'text',
                backgroundClip: 'text',
                color: 'transparent',
              }}
            >
              you wish existed.
            </span>
          </h1>

          <p
            className="mb-10 max-w-[460px] leading-[1.80]"
            style={{
              fontSize: 'clamp(0.9rem, 1.3vw, 1rem)',
              color: 'rgba(255,255,255,0.46)',
              letterSpacing: '-0.01em',
            }}
          >
            Start with the work you know matters. Fresh Collective gives you a place to shape it
            into pathways, gatherings, resources, and community.
          </p>

          <div className="flex flex-wrap items-center justify-center gap-3">
            <button
              type="button"
              onClick={scrollToForm}
              className="inline-flex items-center rounded-xl px-7 py-3.5 text-[15px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                boxShadow: '0 2px 20px rgba(56,160,158,0.40)',
              }}
            >
              Create your collective
            </button>
            <Link
              href="/creator-studio"
              className="inline-flex items-center rounded-xl px-7 py-3.5 text-[15px] font-semibold text-white transition-all hover:-translate-y-px"
              style={{
                border: '1px solid rgba(255,255,255,0.16)',
                background: 'rgba(255,255,255,0.04)',
              }}
            >
              Back to Creator Studio
            </Link>
          </div>
        </div>
      </section>

      {/* ── Section 2: Visual preview ─────────────────────────────────────── */}
      <section
        className="overflow-hidden px-4 py-14"
        style={{
          background:
            'linear-gradient(180deg, #071824 0%, #0D2030 30%, #E8EFEE 85%, #F0F4F3 100%)',
        }}
      >
        <div className="mx-auto max-w-4xl">
          {/* Floating badge */}
          <div className="mb-8 flex justify-center">
            <span
              className="rounded-full px-5 py-2 text-[12px] font-semibold text-white"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                boxShadow: '0 4px 16px rgba(56,160,158,0.35)',
              }}
            >
              Your first collective starts here.
            </span>
          </div>

          {/* Three-card display */}
          <div className="flex items-stretch justify-center gap-3 md:gap-5">
            {/* Left card — partially visible on desktop */}
            <div
              className="hidden w-[220px] shrink-0 md:block"
              style={{
                transform: 'scale(0.90) translateX(12px)',
                opacity: 0.55,
                transformOrigin: 'right center',
              }}
            >
              <CollectiveCard collective={EXAMPLE_COLLECTIVES[0]} />
            </div>

            {/* Centre card — featured */}
            <div className="w-full max-w-[280px] shrink-0">
              <CollectiveCard collective={EXAMPLE_COLLECTIVES[1]} featured />
            </div>

            {/* Right card — partially visible on desktop */}
            <div
              className="hidden w-[220px] shrink-0 md:block"
              style={{
                transform: 'scale(0.90) translateX(-12px)',
                opacity: 0.55,
                transformOrigin: 'left center',
              }}
            >
              <CollectiveCard collective={EXAMPLE_COLLECTIVES[2]} />
            </div>
          </div>
        </div>
      </section>

      {/* ── Section 3: Create form ────────────────────────────────────────── */}
      <section id="create-form" style={{ background: '#FAFAF8' }}>
        <div className="mx-auto max-w-2xl px-6 py-16">

          <div className="mb-10">
            <p
              className="mb-2 text-[11px] font-bold uppercase tracking-[0.18em]"
              style={{ color: '#38A09E' }}
            >
              Start building
            </p>
            <h2 className="mb-2 font-serif text-2xl text-navy-900 md:text-3xl">
              Start with the foundation.
            </h2>
            <p className="text-[14px] leading-relaxed text-slate-400">
              You can change this later. For now, give your collective enough shape to begin.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-7">

            {/* 1. Collective name */}
            <div>
              <label
                htmlFor="collective-name"
                className="mb-2 block text-[13.5px] font-semibold text-navy-900"
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
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-[14px] text-navy-900 placeholder:text-slate-300 transition-colors focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
              />
            </div>

            {/* 2. Short tagline */}
            <div>
              <label
                htmlFor="collective-tagline"
                className="mb-2 block text-[13.5px] font-semibold text-navy-900"
              >
                Short tagline
              </label>
              <input
                id="collective-tagline"
                type="text"
                value={tagline}
                onChange={(e) => setTagline(e.target.value)}
                placeholder="A guided collective for people ready to live with more clarity and intention."
                maxLength={300}
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-[14px] text-navy-900 placeholder:text-slate-300 transition-colors focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
              />
            </div>

            {/* 3. Who is this for */}
            <div>
              <label
                htmlFor="collective-who"
                className="mb-2 block text-[13.5px] font-semibold text-navy-900"
              >
                Who is this for?
              </label>
              <textarea
                id="collective-who"
                value={whoFor}
                onChange={(e) => setWhoFor(e.target.value)}
                placeholder="Describe the people this collective is designed for."
                rows={3}
                className="w-full resize-none rounded-xl border border-slate-200 bg-white px-4 py-3 text-[14px] text-navy-900 placeholder:text-slate-300 transition-colors focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
              />
            </div>

            {/* 4. What change */}
            <div>
              <label
                htmlFor="collective-change"
                className="mb-2 block text-[13.5px] font-semibold text-navy-900"
              >
                What change does this collective help people practise?
              </label>
              <textarea
                id="collective-change"
                value={whatChange}
                onChange={(e) => setWhatChange(e.target.value)}
                placeholder="What will people begin to see, feel, practise, or live differently?"
                rows={3}
                className="w-full resize-none rounded-xl border border-slate-200 bg-white px-4 py-3 text-[14px] text-navy-900 placeholder:text-slate-300 transition-colors focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/20"
              />
            </div>

            {/* 5. Category */}
            <div>
              <p className="mb-3 text-[13.5px] font-semibold text-navy-900">Category</p>
              <div className="flex flex-wrap gap-2">
                {CATEGORIES.map((cat) => (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => setCategory(cat === category ? '' : cat)}
                    className="rounded-full border px-3.5 py-1.5 text-[13px] font-medium transition-all"
                    style={{
                      borderColor: category === cat ? '#38A09E' : '#e2e8f0',
                      background: category === cat ? 'rgba(56,160,158,0.10)' : 'white',
                      color: category === cat ? '#38A09E' : '#94a3b8',
                    }}
                  >
                    {cat}
                  </button>
                ))}
              </div>
              {/* TODO: persist category when Space model supports a category field */}
              <p className="mt-2 text-[11.5px] text-slate-300">
                Saved when categories are supported. Helps members find your collective.
              </p>
            </div>

            {/* 6. Start as */}
            <div>
              <p className="mb-3 text-[13.5px] font-semibold text-navy-900">Start as</p>
              <div className="grid gap-3 sm:grid-cols-2">
                {(
                  [
                    {
                      value: 'draft' as const,
                      label: 'Draft',
                      desc: 'Private while you build. You decide when to open the doors.',
                    },
                    {
                      value: 'publish_later' as const,
                      label: 'Publish when ready',
                      desc: "Start as a draft and open it up once it's ready to hold people.",
                    },
                  ] as const
                ).map((opt) => (
                  <label
                    key={opt.value}
                    className="flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-all"
                    style={{
                      borderColor:
                        startAs === opt.value ? 'rgba(56,160,158,0.36)' : '#e2e8f0',
                      background:
                        startAs === opt.value ? 'rgba(56,160,158,0.05)' : 'white',
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
                      <p className="text-[13.5px] font-medium text-navy-900">{opt.label}</p>
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
                className="rounded-xl px-4 py-3 text-[13.5px]"
                style={{
                  background: 'rgba(239,68,68,0.06)',
                  color: '#dc2626',
                  border: '1px solid rgba(239,68,68,0.20)',
                }}
              >
                {error}
              </p>
            )}

            {/* Submit */}
            <div className="pt-2">
              <button
                type="submit"
                disabled={saving}
                className="inline-flex w-full items-center justify-center rounded-xl px-7 py-3.5 text-[15px] font-semibold text-white transition-all hover:opacity-90 disabled:opacity-60 sm:w-auto"
                style={{
                  background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                  boxShadow: '0 2px 16px rgba(56,160,158,0.30)',
                }}
              >
                {saving ? 'Creating…' : 'Create collective'}
              </button>
            </div>

          </form>
        </div>
      </section>

    </div>
  )
}
