'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

const TOTAL_STEPS = 4

const INTERESTS = [
  { id: 'leadership', label: 'Leadership' },
  { id: 'nervous_system', label: 'Nervous system' },
  { id: 'creativity', label: 'Creativity' },
  { id: 'business', label: 'Business & work' },
  { id: 'identity', label: 'Identity' },
  { id: 'wellbeing', label: 'Wellbeing' },
  { id: 'facilitation', label: 'Facilitation' },
  { id: 'self_awareness', label: 'Self-awareness' },
]

interface Props {
  firstName: string | null
}

export default function OnboardingFlow({ firstName }: Props) {
  const router = useRouter()
  const [step, setStep] = useState(1)
  const [selectedInterests, setSelectedInterests] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)

  function toggleInterest(id: string) {
    setSelectedInterests((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    )
  }

  async function handleComplete() {
    setSubmitting(true)
    try {
      await fetch(apiUrl('/api/auth/me/complete-onboarding'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interests: selectedInterests }),
      })
    } catch {
      // Non-critical — proceed regardless
    }
    router.push('/spaces')
    router.refresh()
  }

  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* Minimal header */}
      <div className="flex items-center justify-between px-8 py-6 md:px-14">
        <span className="font-serif text-base text-navy-900">Fresh Collective</span>
        <StepDots current={step} total={TOTAL_STEPS} />
      </div>

      {/* Step content */}
      <main className="flex flex-1 items-center justify-center px-6 py-10 md:px-14">
        <div className="w-full max-w-lg">
          {step === 1 && (
            <StepWelcome firstName={firstName} onNext={() => setStep(2)} />
          )}
          {step === 2 && (
            <StepInterests
              selected={selectedInterests}
              onToggle={toggleInterest}
              onBack={() => setStep(1)}
              onNext={() => setStep(3)}
            />
          )}
          {step === 3 && (
            <StepHowItWorks onBack={() => setStep(2)} onNext={() => setStep(4)} />
          )}
          {step === 4 && (
            <StepStartingPoint
              onBack={() => setStep(3)}
              onComplete={handleComplete}
              submitting={submitting}
            />
          )}
        </div>
      </main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Progress dots
// ---------------------------------------------------------------------------

function StepDots({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-2">
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          className={[
            'h-1.5 rounded-full transition-all duration-300',
            i + 1 === current
              ? 'w-6 bg-teal-500'
              : i + 1 < current
              ? 'w-1.5 bg-teal-300'
              : 'w-1.5 bg-slate-200',
          ].join(' ')}
        />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Navigation buttons
// ---------------------------------------------------------------------------

function NavRow({
  onBack,
  onNext,
  nextLabel = 'Continue',
  disabled = false,
}: {
  onBack?: () => void
  onNext?: () => void
  nextLabel?: string
  disabled?: boolean
}) {
  return (
    <div className="mt-10 flex items-center gap-4">
      {onBack && (
        <button
          type="button"
          onClick={onBack}
          className="text-sm text-slate-400 hover:text-navy-700 transition-colors"
        >
          ← Back
        </button>
      )}
      {onNext && (
        <button
          type="button"
          onClick={onNext}
          disabled={disabled}
          className="ml-auto rounded-lg bg-navy-900 px-7 py-3 text-sm font-medium text-white transition-colors hover:bg-navy-800 disabled:opacity-40"
        >
          {nextLabel}
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 1 — Welcome
// ---------------------------------------------------------------------------

function StepWelcome({ firstName, onNext }: { firstName: string | null; onNext: () => void }) {
  return (
    <div>
      <div className="mb-5 h-px w-8 bg-gold-500" />
      <h1 className="mb-6 font-serif text-4xl leading-snug text-navy-900 md:text-5xl">
        {firstName ? `Welcome, ${firstName}.` : 'Welcome.'}
      </h1>
      <div className="space-y-4 text-[16px] leading-[1.85] text-slate-600">
        <p>
          Fresh Collective is a place for experiential learning — guided pathways,
          live experiences, and a real community supporting the work.
        </p>
        <p>
          This isn&apos;t a course library. It&apos;s a living environment
          designed to move with you, at a pace that honours how change actually works.
        </p>
      </div>
      <NavRow onNext={onNext} nextLabel="Let's begin" />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 2 — Interests
// ---------------------------------------------------------------------------

function StepInterests({
  selected,
  onToggle,
  onBack,
  onNext,
}: {
  selected: string[]
  onToggle: (id: string) => void
  onBack: () => void
  onNext: () => void
}) {
  return (
    <div>
      <div className="mb-5 h-px w-8 bg-gold-500" />
      <h2 className="mb-3 font-serif text-3xl text-navy-900">
        What are you here to explore?
      </h2>
      <p className="mb-8 text-sm text-slate-500">
        Choose anything that resonates. This helps us shape your experience — you can always change it later.
      </p>
      <div className="flex flex-wrap gap-2.5">
        {INTERESTS.map((interest) => {
          const active = selected.includes(interest.id)
          return (
            <button
              key={interest.id}
              type="button"
              onClick={() => onToggle(interest.id)}
              className={[
                'rounded-full border px-4 py-2 text-sm font-medium transition-colors',
                active
                  ? 'border-teal-500 bg-teal-50 text-teal-700'
                  : 'border-border bg-surface text-slate-600 hover:border-slate-300 hover:text-navy-800',
              ].join(' ')}
            >
              {interest.label}
            </button>
          )
        })}
      </div>
      <p className="mt-4 text-xs text-slate-400">Select as many as you like, or skip if you&apos;re unsure.</p>
      <NavRow onBack={onBack} onNext={onNext} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 3 — How it works
// ---------------------------------------------------------------------------

const HOW_IT_WORKS = [
  {
    label: 'Pathways',
    accent: 'bg-teal-500',
    description:
      'Structured learning sequences you move through at your own pace. Each step invites reflection, not just reading.',
  },
  {
    label: 'Community',
    accent: 'bg-gold-500',
    description:
      'Real conversations with people on similar paths. A place to share, ask, and be witnessed.',
  },
  {
    label: 'Events',
    accent: 'bg-navy-400',
    description:
      'Live experiences with the collective. Calls, workshops, and shared moments that deepen the learning.',
  },
]

function StepHowItWorks({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  return (
    <div>
      <div className="mb-5 h-px w-8 bg-gold-500" />
      <h2 className="mb-3 font-serif text-3xl text-navy-900">
        How learning works here.
      </h2>
      <p className="mb-8 text-sm text-slate-500">
        Three layers, working together.
      </p>
      <div className="space-y-4">
        {HOW_IT_WORKS.map((item) => (
          <div
            key={item.label}
            className="flex gap-5 rounded-xl border border-border bg-surface px-6 py-5"
          >
            <div className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${item.accent}`} />
            <div>
              <p className="mb-1 text-sm font-semibold text-navy-800">{item.label}</p>
              <p className="text-sm leading-relaxed text-slate-500">{item.description}</p>
            </div>
          </div>
        ))}
      </div>
      <NavRow onBack={onBack} onNext={onNext} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 4 — Starting point
// ---------------------------------------------------------------------------

function StepStartingPoint({
  onBack,
  onComplete,
  submitting,
}: {
  onBack: () => void
  onComplete: () => void
  submitting: boolean
}) {
  return (
    <div>
      <div className="mb-5 h-px w-8 bg-gold-500" />
      <h2 className="mb-3 font-serif text-3xl text-navy-900">
        Where you begin.
      </h2>
      <p className="mb-8 text-sm text-slate-500">
        Fresh Collective is made up of different collectives, pathways and live experiences.
        Start by exploring what&apos;s available, then continue from the space you joined.
      </p>

      {/* Explore card */}
      <div
        className="mb-6 rounded-xl border border-teal-200 bg-teal-50/40 px-7 py-6"
        style={{ borderLeft: '3px solid var(--color-teal-500)' }}
      >
        <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-teal-600">
          Your starting point
        </p>
        <p className="mb-2 font-serif text-xl text-navy-900">Explore Collectives</p>
        <p className="text-sm leading-relaxed text-slate-500">
          Browse available collectives and continue from the one you joined. Everything is here —
          pathways, community, and live sessions.
        </p>
      </div>

      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={onBack}
          className="text-sm text-slate-400 hover:text-navy-700 transition-colors"
        >
          ← Back
        </button>
        <button
          type="button"
          onClick={onComplete}
          disabled={submitting}
          className="ml-auto rounded-lg bg-teal-600 px-8 py-3 text-sm font-medium text-white transition-colors hover:bg-teal-700 disabled:opacity-40"
        >
          {submitting ? 'Opening…' : 'Explore Collectives →'}
        </button>
      </div>
    </div>
  )
}
