'use client'

import { useState, useRef } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import { COLLECTIVE_THEMES } from '@/lib/themes'
import { MAX_COLLECTIVES_FOR_FOUNDING_CREATOR } from '@/lib/creatorPlan'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FormState {
  name: string
  tagline: string
  themes: string[]
  description: string
  isPublic: boolean
}

// ---------------------------------------------------------------------------
// Limit reached
// ---------------------------------------------------------------------------

function LimitReached() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center px-8 py-16 text-center">
      <div
        className="mb-6 flex h-14 w-14 items-center justify-center rounded-full"
        style={{ background: 'rgba(0,0,0,0.05)', border: '1.5px solid rgba(0,0,0,0.10)' }}
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
      <p className="mb-8 max-w-[400px] text-[15px] leading-relaxed text-slate-500">
        Founding Creator access includes up to {MAX_COLLECTIVES_FOR_FOUNDING_CREATOR} collectives.
        Creator Plus is coming soon for creators who need more room to build.
      </p>
      <div className="flex flex-wrap items-center justify-center gap-3">
        <Link
          href="/creator-studio"
          className="rounded-xl border border-slate-200 bg-white px-6 py-2.5 text-[14px] font-medium text-slate-600 transition-colors hover:border-teal-200 hover:text-teal-700"
        >
          Back to Studio Home
        </Link>
        <span
          className="rounded-xl px-6 py-2.5 text-[14px] font-medium"
          style={{ background: 'rgba(56,160,158,0.10)', color: '#38A09E', cursor: 'default' }}
        >
          Creator Plus coming soon
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------

const STEP_LABELS = ['Foundation', 'Description', 'Finish']

function StepIndicator({ current }: { current: number }) {
  return (
    <div className="mb-8 flex items-center gap-0">
      {STEP_LABELS.map((label, i) => {
        const step = i + 1
        const done = step < current
        const active = step === current
        return (
          <div key={label} className="flex items-center">
            <div className="flex flex-col items-center">
              <div
                className="flex h-7 w-7 items-center justify-center rounded-full text-[12px] font-semibold transition-all"
                style={{
                  background: done
                    ? 'rgba(56,160,158,0.18)'
                    : active
                    ? 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)'
                    : 'rgba(0,0,0,0.05)',
                  color: done ? '#38A09E' : active ? '#fff' : '#94a3b8',
                  border: done ? '1.5px solid rgba(56,160,158,0.35)' : 'none',
                }}
              >
                {done ? (
                  <svg width="12" height="9" viewBox="0 0 12 9" fill="none" aria-hidden="true">
                    <path d="M1 4l3.5 3.5L11 1" stroke="#38A09E" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : (
                  step
                )}
              </div>
              <span
                className="mt-1 text-[11px] font-medium"
                style={{ color: active ? '#38A09E' : done ? '#38A09E' : '#94a3b8' }}
              >
                {label}
              </span>
            </div>
            {i < STEP_LABELS.length - 1 && (
              <div
                className="mb-4 mx-2 h-px w-10 sm:w-16 transition-colors"
                style={{ background: done ? 'rgba(56,160,158,0.40)' : 'rgba(0,0,0,0.10)' }}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 1 — Foundation: name, tagline, themes
// ---------------------------------------------------------------------------

function Step1({
  form,
  onChange,
  onNext,
  error,
}: {
  form: FormState
  onChange: (patch: Partial<FormState>) => void
  onNext: () => void
  error: string | null
}) {
  function toggleTheme(t: string) {
    const next = form.themes.includes(t)
      ? form.themes.filter((x) => x !== t)
      : [...form.themes, t]
    onChange({ themes: next })
  }

  function handleNext() {
    if (!form.name.trim()) {
      document.getElementById('collective-name')?.focus()
      return
    }
    onNext()
  }

  return (
    <div className="space-y-6">
      {/* Name */}
      <div>
        <label htmlFor="collective-name" className="mb-1.5 block text-[14px] font-semibold text-navy-900">
          Collective name <span aria-hidden="true" style={{ color: '#38A09E' }}>*</span>
        </label>
        <input
          id="collective-name"
          type="text"
          value={form.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="e.g. Living Intentionally"
          maxLength={200}
          autoFocus
          className="w-full rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-400 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
        />
      </div>

      {/* Tagline */}
      <div>
        <label htmlFor="collective-tagline" className="mb-1.5 block text-[14px] font-semibold text-navy-900">
          Short tagline <span className="font-normal text-slate-400">(optional)</span>
        </label>
        <input
          id="collective-tagline"
          type="text"
          value={form.tagline}
          onChange={(e) => onChange({ tagline: e.target.value })}
          placeholder="A guided collective for people ready to live with more clarity."
          maxLength={300}
          className="w-full rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-400 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
        />
      </div>

      {/* Themes */}
      <div>
        <p className="mb-2.5 text-[14px] font-semibold text-navy-900">
          Themes <span className="font-normal text-slate-400">(choose any that apply)</span>
        </p>
        <div className="flex flex-wrap gap-2">
          {COLLECTIVE_THEMES.map((theme) => {
            const selected = form.themes.includes(theme)
            return (
              <button
                key={theme}
                type="button"
                onClick={() => toggleTheme(theme)}
                className="rounded-full border px-3 py-1.5 text-[13px] font-medium transition-all hover:border-teal-300 hover:text-teal-600"
                style={{
                  borderColor: selected ? '#38A09E' : '#e2e8f0',
                  background: selected ? 'rgba(56,160,158,0.10)' : 'transparent',
                  color: selected ? '#2d8a88' : '#64748b',
                }}
              >
                {theme}
              </button>
            )
          })}
        </div>
      </div>

      {error && (
        <div
          className="rounded-xl px-4 py-3 text-[13px]"
          style={{ background: 'rgba(239,68,68,0.06)', color: '#dc2626', border: '1px solid rgba(239,68,68,0.18)' }}
        >
          {error}
        </div>
      )}

      <div className="flex items-center gap-5 pt-2">
        <button
          type="button"
          onClick={handleNext}
          className="inline-flex items-center rounded-xl px-7 py-2.5 text-[15px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)', boxShadow: '0 3px 18px rgba(56,160,158,0.36)' }}
        >
          Continue
        </button>
        <Link href="/creator-studio" className="text-[13px] text-slate-500 transition-colors hover:text-slate-700">
          Cancel
        </Link>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 2 — Description & visibility
// ---------------------------------------------------------------------------

function Step2({
  form,
  onChange,
  onBack,
  onNext,
}: {
  form: FormState
  onChange: (patch: Partial<FormState>) => void
  onBack: () => void
  onNext: () => void
}) {
  return (
    <div className="space-y-6">
      {/* Description */}
      <div>
        <label htmlFor="collective-description" className="mb-1.5 block text-[14px] font-semibold text-navy-900">
          Description <span className="font-normal text-slate-400">(optional)</span>
        </label>
        <p className="mb-2 text-[13px] text-slate-500">
          Help people understand what your collective is for and who it is designed to support.
        </p>
        <textarea
          id="collective-description"
          value={form.description}
          onChange={(e) => onChange({ description: e.target.value })}
          placeholder="Describe what this collective offers and the transformation it supports."
          rows={5}
          autoFocus
          className="w-full resize-none rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-2.5 text-[14px] text-navy-900 placeholder:text-slate-400 transition-colors focus:border-teal-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-teal-400/20"
        />
      </div>

      {/* Visibility */}
      <div>
        <p className="mb-2.5 text-[14px] font-semibold text-navy-900">Visibility</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {([
            { value: false, label: 'Private', desc: 'Only invited members can join. Build it before you open it.' },
            { value: true, label: 'Public', desc: 'Anyone can find and join your collective.' },
          ] as const).map((opt) => (
            <label
              key={String(opt.value)}
              className="flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-all"
              style={{
                borderColor: form.isPublic === opt.value ? 'rgba(56,160,158,0.40)' : '#e2e8f0',
                background: form.isPublic === opt.value ? 'rgba(56,160,158,0.06)' : 'transparent',
              }}
            >
              <input
                type="radio"
                name="visibility"
                checked={form.isPublic === opt.value}
                onChange={() => onChange({ isPublic: opt.value })}
                className="mt-0.5 accent-teal-500"
              />
              <div>
                <p className="text-[14px] font-medium text-navy-900">{opt.label}</p>
                <p className="mt-0.5 text-[13px] text-slate-500">{opt.desc}</p>
              </div>
            </label>
          ))}
        </div>
        <p className="mt-2 text-[12px] text-slate-400">
          You can change this at any time in Settings.
        </p>
      </div>

      <div className="flex items-center gap-5 pt-2">
        <button
          type="button"
          onClick={onNext}
          className="inline-flex items-center rounded-xl px-7 py-2.5 text-[15px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)', boxShadow: '0 3px 18px rgba(56,160,158,0.36)' }}
        >
          Continue
        </button>
        <button
          type="button"
          onClick={onBack}
          className="text-[13px] text-slate-500 transition-colors hover:text-slate-700"
        >
          Back
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 3 — Banner + first move + submit
// ---------------------------------------------------------------------------

function Step3({
  form,
  onBack,
  onSubmit,
  saving,
  error,
}: {
  form: FormState
  onBack: () => void
  onSubmit: (bannerFile: File | null) => void
  saving: boolean
  error: string | null
}) {
  const [bannerFile, setBannerFile] = useState<File | null>(null)
  const [bannerPreview, setBannerPreview] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null
    setBannerFile(file)
    if (file) {
      const url = URL.createObjectURL(file)
      setBannerPreview(url)
    } else {
      setBannerPreview(null)
    }
  }

  return (
    <div className="space-y-6">
      {/* Banner */}
      <div>
        <p className="mb-1.5 text-[14px] font-semibold text-navy-900">
          Banner image <span className="font-normal text-slate-400">(optional)</span>
        </p>
        <p className="mb-3 text-[13px] text-slate-500">
          Wide image recommended (16:9). JPG or PNG. You can add or change this later.
        </p>

        {bannerPreview ? (
          <div className="mb-3 overflow-hidden rounded-xl border border-slate-200">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={bannerPreview} alt="Banner preview" className="h-40 w-full object-cover" />
          </div>
        ) : (
          <div
            className="mb-3 flex h-32 w-full cursor-pointer items-center justify-center rounded-xl border-2 border-dashed transition-colors hover:border-teal-300 hover:bg-teal-50/40"
            style={{ borderColor: '#e2e8f0' }}
            onClick={() => fileRef.current?.click()}
          >
            <div className="text-center">
              <svg className="mx-auto mb-1.5 text-slate-300" width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <rect x="3" y="3" width="18" height="18" rx="3" stroke="currentColor" strokeWidth="1.5" />
                <circle cx="8.5" cy="8.5" r="1.5" stroke="currentColor" strokeWidth="1.5" />
                <path d="M3 16l5-5 4 4 3-3 6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <p className="text-[13px] text-slate-400">Click to choose image</p>
            </div>
          </div>
        )}

        <div className="flex items-center gap-2">
          <label className="cursor-pointer rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-navy-900 transition-colors hover:border-teal-300 hover:text-teal-700">
            {bannerFile ? 'Replace' : 'Choose image'}
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png"
              className="sr-only"
              onChange={handleFileChange}
            />
          </label>
          {bannerFile && (
            <button
              type="button"
              onClick={() => { setBannerFile(null); setBannerPreview(null) }}
              className="text-[12px] text-slate-400 transition-colors hover:text-slate-600"
            >
              Remove
            </button>
          )}
        </div>
      </div>

      {/* Summary */}
      <div
        className="rounded-xl px-5 py-4"
        style={{ background: 'rgba(56,160,158,0.05)', border: '1px solid rgba(56,160,158,0.15)' }}
      >
        <p className="mb-1 text-[12px] font-semibold uppercase tracking-[0.12em]" style={{ color: '#38A09E' }}>
          Ready to create
        </p>
        <p className="text-[15px] font-semibold text-navy-900">{form.name}</p>
        {form.tagline && <p className="mt-0.5 text-[13px] text-slate-500">{form.tagline}</p>}
        {form.themes.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {form.themes.map((t) => (
              <span
                key={t}
                className="rounded-full px-2 py-0.5 text-[11px] font-medium"
                style={{ background: 'rgba(56,160,158,0.12)', color: '#2d8a88' }}
              >
                {t}
              </span>
            ))}
          </div>
        )}
        <p className="mt-2 text-[12px] text-slate-400">
          {form.isPublic ? 'Public' : 'Private'} · Will be created as a draft
        </p>
      </div>

      {error && (
        <div
          className="rounded-xl px-4 py-3 text-[13px]"
          style={{ background: 'rgba(239,68,68,0.06)', color: '#dc2626', border: '1px solid rgba(239,68,68,0.18)' }}
        >
          {error}
        </div>
      )}

      <div className="flex items-center gap-5 pt-2">
        <button
          type="button"
          disabled={saving}
          onClick={() => onSubmit(bannerFile)}
          className="inline-flex items-center rounded-xl px-7 py-2.5 text-[15px] font-semibold text-white transition-all hover:-translate-y-px hover:opacity-90 disabled:translate-y-0 disabled:opacity-60"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)', boxShadow: '0 3px 18px rgba(56,160,158,0.36)' }}
        >
          {saving ? 'Creating…' : 'Create collective'}
        </button>
        <button
          type="button"
          onClick={onBack}
          disabled={saving}
          className="text-[13px] text-slate-500 transition-colors hover:text-slate-700 disabled:opacity-50"
        >
          Back
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function CreateCollectiveFlow({ existingCount }: { existingCount: number }) {
  const router = useRouter()
  const [step, setStep] = useState(1)
  const [form, setForm] = useState<FormState>({
    name: '',
    tagline: '',
    themes: [],
    description: '',
    isPublic: false,
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function patch(update: Partial<FormState>) {
    setForm((f) => ({ ...f, ...update }))
  }

  function handleStep1Next() {
    if (!form.name.trim()) {
      setError('Please enter a name for your collective.')
      return
    }
    setError(null)
    setStep(2)
  }

  async function handleSubmit(bannerFile: File | null) {
    setSaving(true)
    setError(null)

    try {
      // 1. Create the space
      const res = await fetch(apiUrl('/api/creator/spaces'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          name: form.name.trim(),
          tagline: form.tagline.trim() || null,
          description: form.description.trim() || null,
          is_public: form.isPublic,
          themes: form.themes,
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

      const space = await res.json()
      const slug: string = space.slug

      // 2. Upload banner if provided
      if (bannerFile) {
        const formData = new FormData()
        formData.append('file', bannerFile)
        await fetch(apiUrl(`/api/creator/spaces/${slug}/cover`), {
          method: 'POST',
          credentials: 'include',
          body: formData,
        })
      }

      // 3. Set as active collective (same mechanism as sidebar switcher)
      document.cookie = `fc_creator_space=${slug}; path=/; max-age=86400`

      // 4. Navigate to setup for the new collective
      router.push('/creator-studio/setup')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
      setSaving(false)
    }
  }

  if (existingCount >= MAX_COLLECTIVES_FOR_FOUNDING_CREATOR) return <LimitReached />

  const stepTitles = [
    'Start with the foundation.',
    'Add a description.',
    'Almost there.',
  ]
  const stepSubtitles = [
    'Give your collective a name and choose the themes it will explore.',
    'Help people understand what your collective is for. You can update this any time.',
    'Add a banner image if you have one ready, then create your collective.',
  ]

  return (
    <div
      className="relative min-h-screen"
      style={{ background: 'linear-gradient(160deg, #EEF3F2 0%, #F7F8FA 50%, #F2F6F5 100%)' }}
    >
      {/* Faint teal glow */}
      <div
        className="pointer-events-none absolute right-0 top-0 h-[640px] w-[640px] translate-x-[38%] -translate-y-[15%] rounded-full"
        aria-hidden="true"
        style={{ background: 'radial-gradient(circle, rgba(56,160,158,0.09) 0%, transparent 65%)' }}
      />

      <div className="relative mx-auto max-w-2xl px-6 py-10">

        {/* Page header */}
        <div className="mb-8">
          <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.18em]" style={{ color: '#38A09E' }}>
            Create your collective
          </p>
          <h1 className="mb-2 font-serif text-[1.875rem] leading-tight text-navy-900 md:text-[2.375rem]">
            {stepTitles[step - 1]}
          </h1>
          <p className="text-[15px] leading-relaxed" style={{ color: '#334155' }}>
            {stepSubtitles[step - 1]}
          </p>
        </div>

        {/* Step indicator */}
        <StepIndicator current={step} />

        {/* Form card */}
        <div
          className="rounded-3xl bg-white px-8 py-8"
          style={{
            border: '1px solid rgba(56,160,158,0.14)',
            boxShadow: '0 8px 40px rgba(0,0,0,0.08), inset 0 1px 0 rgba(255,255,255,0.80)',
          }}
        >
          {step === 1 && (
            <Step1
              form={form}
              onChange={patch}
              onNext={handleStep1Next}
              error={error}
            />
          )}
          {step === 2 && (
            <Step2
              form={form}
              onChange={patch}
              onBack={() => setStep(1)}
              onNext={() => setStep(3)}
            />
          )}
          {step === 3 && (
            <Step3
              form={form}
              onBack={() => setStep(2)}
              onSubmit={handleSubmit}
              saving={saving}
              error={error}
            />
          )}
        </div>

        <p className="mt-6 text-center text-[12px] text-slate-400">
          Founding Creator access includes up to {MAX_COLLECTIVES_FOR_FOUNDING_CREATOR} collectives.
        </p>

      </div>
    </div>
  )
}
