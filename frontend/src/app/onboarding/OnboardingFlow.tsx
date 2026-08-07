'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import OnboardingHero from '@/components/onboarding/OnboardingHero'

const TOTAL_STEPS = 4

export interface OnboardingHeroArt {
  welcome: string | null
  interests: string | null
  howItWorks: string | null
  arrival: string | null
}

const EMPTY_HERO_ART: OnboardingHeroArt = {
  welcome: null,
  interests: null,
  howItWorks: null,
  arrival: null,
}

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
  heroArt?: OnboardingHeroArt
}

// Warm palette — the orientation is a short journey through the Fresh
// Collective world, so the surfaces stay cream + gold-tinted rather
// than the platform's cooler working-day white.
const NAVY = '#0C1826'
const TEAL = '#38A09E'
const TEAL_DEEP = '#246B6A'
const GOLD = '#D4B048'
const CREAM = '#FBF6EA'
const INK_BODY = 'rgba(12, 24, 38, 0.78)'
const INK_SOFT = 'rgba(12, 24, 38, 0.62)'

export default function OnboardingFlow({ firstName, heroArt = EMPTY_HERO_ART }: Props) {
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
    // Return to Your World rather than Explore Collectives — the
    // orientation is a supplement to Your World, not a jumping-off
    // point to discovery.
    router.push('/dashboard')
    router.refresh()
  }

  return (
    <div
      className="flex min-h-screen flex-col"
      style={{
        background:
          'radial-gradient(120% 60% at 50% 0%, rgba(212, 176, 72, 0.12), transparent 60%),' +
          'radial-gradient(90% 70% at 50% 100%, rgba(56, 160, 158, 0.09), transparent 65%),' +
          `linear-gradient(180deg, ${CREAM} 0%, #FFFFFF 100%)`,
        color: NAVY,
      }}
    >
      {/* Minimal warm header */}
      <div className="flex items-center justify-between px-8 py-7 md:px-14">
        <span
          className="font-serif text-[15px]"
          style={{ color: NAVY, letterSpacing: '0.01em' }}
        >
          Fresh Collective
        </span>
        {step > 1 ? (
          <StepDots current={step} total={TOTAL_STEPS} />
        ) : (
          <span aria-hidden="true" />
        )}
      </div>

      {/* Step content */}
      <main className="flex flex-1 items-center justify-center px-6 pb-16 md:px-14">
        <div className="w-full max-w-[720px]">
          {step === 1 && (
            <StepWelcome firstName={firstName} heroUrl={heroArt.welcome} onNext={() => setStep(2)} />
          )}
          {step === 2 && (
            <StepInterests
              selected={selectedInterests}
              onToggle={toggleInterest}
              heroUrl={heroArt.interests}
              onBack={() => setStep(1)}
              onNext={() => setStep(3)}
            />
          )}
          {step === 3 && (
            <StepHowItWorks
              heroUrl={heroArt.howItWorks}
              onBack={() => setStep(2)}
              onNext={() => setStep(4)}
            />
          )}
          {step === 4 && (
            <StepStartingPoint
              heroUrl={heroArt.arrival}
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
    <div className="flex items-center gap-2" aria-hidden="true">
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          className="rounded-full transition-all duration-500"
          style={{
            height: 2,
            width: i + 1 === current ? 22 : 6,
            background:
              i + 1 === current
                ? TEAL
                : i + 1 < current
                  ? 'rgba(56, 160, 158, 0.45)'
                  : 'rgba(12, 24, 38, 0.14)',
          }}
        />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared navigation row
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
    <div className="mt-12 flex items-center gap-4">
      {onBack ? (
        <button
          type="button"
          onClick={onBack}
          className="text-[13px] transition-opacity hover:opacity-70"
          style={{ color: INK_SOFT }}
        >
          ← Back
        </button>
      ) : <span />}
      {onNext && (
        <button
          type="button"
          onClick={onNext}
          disabled={disabled}
          className="ml-auto rounded-full px-7 py-3 text-[13.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          style={{
            background: `linear-gradient(135deg, ${TEAL} 0%, #55B8B6 100%)`,
            letterSpacing: '0.06em',
          }}
        >
          {nextLabel}
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Ambient artwork — small SVG scenes rendered as the graceful fallback
// inside OnboardingHero when no admin-uploaded imagery exists yet.
// ---------------------------------------------------------------------------

function HorizonScene() {
  return (
    <svg viewBox="0 0 200 200" className="h-full w-full">
      <defs>
        <radialGradient id="sunGrad" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor={GOLD} stopOpacity="0.85" />
          <stop offset="100%" stopColor={GOLD} stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="100" cy="82" r="60" fill="url(#sunGrad)" />
      <circle cx="100" cy="82" r="18" fill={GOLD} opacity="0.75" />
      <path d="M 12 140 Q 100 130 188 140" stroke={TEAL} strokeWidth="1.2" fill="none" opacity="0.55" />
      <path d="M 24 160 Q 100 152 176 160" stroke={TEAL} strokeWidth="0.9" fill="none" opacity="0.38" />
      <path d="M 40 178 Q 100 172 160 178" stroke={TEAL} strokeWidth="0.7" fill="none" opacity="0.24" />
    </svg>
  )
}

function CompassScene() {
  return (
    <svg viewBox="0 0 200 200" className="h-full w-full">
      <circle cx="100" cy="100" r="60" fill="none" stroke={TEAL} strokeWidth="1.2" opacity="0.35" />
      <circle cx="100" cy="100" r="42" fill="none" stroke={TEAL} strokeWidth="0.9" opacity="0.25" />
      <path d="M 100 46 L 108 100 L 100 154 L 92 100 Z" fill={GOLD} opacity="0.75" />
      <path d="M 46 100 L 100 92 L 154 100 L 100 108 Z" fill={TEAL} opacity="0.55" />
      <circle cx="100" cy="100" r="3" fill={NAVY} />
    </svg>
  )
}

function ThreeLightsScene() {
  return (
    <svg viewBox="0 0 200 200" className="h-full w-full">
      <defs>
        <radialGradient id="lightA" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor={TEAL} stopOpacity="0.55" />
          <stop offset="100%" stopColor={TEAL} stopOpacity="0" />
        </radialGradient>
        <radialGradient id="lightB" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor={GOLD} stopOpacity="0.60" />
          <stop offset="100%" stopColor={GOLD} stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="60" cy="100" r="34" fill="url(#lightA)" />
      <circle cx="100" cy="100" r="40" fill="url(#lightB)" />
      <circle cx="140" cy="100" r="34" fill="url(#lightA)" />
      <circle cx="60" cy="100" r="4" fill={TEAL} />
      <circle cx="100" cy="100" r="5" fill={GOLD} opacity="0.9" />
      <circle cx="140" cy="100" r="4" fill={TEAL} />
      <path d="M 30 148 Q 100 138 170 148" stroke={NAVY} strokeWidth="0.6" fill="none" opacity="0.20" />
    </svg>
  )
}

function ArchipelagoScene() {
  return (
    <svg viewBox="0 0 200 200" className="h-full w-full">
      <path d="M 10 130 Q 100 122 190 130 L 190 200 L 10 200 Z" fill={TEAL} opacity="0.12" />
      <ellipse cx="52" cy="118" rx="22" ry="9" fill={NAVY} opacity="0.30" />
      <ellipse cx="52" cy="112" rx="16" ry="6" fill={GOLD} opacity="0.55" />
      <ellipse cx="112" cy="128" rx="30" ry="11" fill={NAVY} opacity="0.32" />
      <ellipse cx="112" cy="120" rx="22" ry="8" fill={GOLD} opacity="0.60" />
      <ellipse cx="164" cy="120" rx="18" ry="7" fill={NAVY} opacity="0.28" />
      <ellipse cx="164" cy="114" rx="12" ry="5" fill={GOLD} opacity="0.50" />
      <path d="M 20 150 Q 100 144 180 150" stroke={TEAL} strokeWidth="0.7" fill="none" opacity="0.45" />
      <path d="M 30 168 Q 100 162 170 168" stroke={TEAL} strokeWidth="0.6" fill="none" opacity="0.30" />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Step 1 — Welcome
// ---------------------------------------------------------------------------

function StepWelcome({
  firstName, heroUrl, onNext,
}: {
  firstName: string | null
  heroUrl: string | null
  onNext: () => void
}) {
  return (
    <div className="text-center">
      <OnboardingHero
        imageUrl={heroUrl}
        alt=""
        fallback={<HorizonScene />}
      />
      <h1
        className="mb-8 font-serif leading-[1.08]"
        style={{
          fontSize: 'clamp(2rem, 4.5vw, 2.75rem)',
          color: NAVY,
          letterSpacing: '-0.02em',
        }}
      >
        {firstName ? `Welcome, ${firstName}.` : 'Welcome.'}
      </h1>
      <div className="mx-auto max-w-[480px] space-y-4">
        <p
          className="text-[15.5px] leading-[1.75]"
          style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
        >
          Fresh Collective is a living world of collectives, pathways,
          gatherings and community &mdash; a place of transformation
          and change rather than consumption.
        </p>
        <p
          className="text-[15.5px] leading-[1.75]"
          style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
        >
          Let us help create the experience that feels most meaningful for you.
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
  heroUrl,
  onBack,
  onNext,
}: {
  selected: string[]
  onToggle: (id: string) => void
  heroUrl: string | null
  onBack: () => void
  onNext: () => void
}) {
  return (
    <div className="text-center">
      <OnboardingHero
        imageUrl={heroUrl}
        alt=""
        fallback={<CompassScene />}
      />
      <h2
        className="mb-4 font-serif leading-tight"
        style={{ fontSize: 'clamp(1.6rem, 3.5vw, 2rem)', color: NAVY }}
      >
        What are you here to explore?
      </h2>
      <p
        className="mx-auto mb-8 max-w-[440px] text-[14.5px] italic leading-relaxed"
        style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
      >
        Choose anything that resonates.
      </p>
      <div className="flex flex-wrap justify-center gap-2.5">
        {INTERESTS.map((interest) => {
          const active = selected.includes(interest.id)
          return (
            <button
              key={interest.id}
              type="button"
              onClick={() => onToggle(interest.id)}
              aria-pressed={active}
              className="rounded-full border px-4 py-2 text-[13.5px] font-medium transition-all"
              style={{
                background: active ? 'rgba(56, 160, 158, 0.10)' : '#FFFFFF',
                borderColor: active ? 'rgba(56, 160, 158, 0.55)' : 'rgba(12, 24, 38, 0.14)',
                color: active ? TEAL_DEEP : NAVY,
              }}
            >
              {interest.label}
            </button>
          )
        })}
      </div>
      <p
        className="mt-5 text-[12px] italic"
        style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
      >
        Select as many as you like, or skip if you&apos;re unsure.
      </p>
      <NavRow onBack={onBack} onNext={onNext} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 3 — How it works
// ---------------------------------------------------------------------------

// Cards on the "How Fresh Collective works" step. Palette is
// intentionally restrained — teal and navy in a checkerboard so the
// four ideas read as a single, cohesive brand surface rather than four
// competing accents.
const HOW_IT_WORKS: {
  label: string
  background: string
  description: string
  Icon: () => React.JSX.Element
}[] = [
  {
    label: 'Pathways',
    background: '#246B6A', // TEAL_DEEP (top-left)
    description:
      'Guided experiences created by Fresh Collective Creators. They may be educational, practical, reflective, self-paced, scheduled — or something entirely their own.',
    Icon: PathwaysMark,
  },
  {
    label: 'Gatherings',
    background: '#0C1826', // NAVY (top-right)
    description:
      'Live experiences that bring people together — online or in person — from workshops, circles and classes to coaching sessions, discussions, celebrations and more.',
    Icon: GatheringsMark,
  },
  {
    label: 'Conversations',
    background: '#0C1826', // NAVY (bottom-left)
    description:
      'Places for members to share, ask questions, respond, exchange ideas and connect with one another between other experiences.',
    Icon: ConversationsMark,
  },
  {
    label: 'Resources',
    background: '#246B6A', // TEAL_DEEP (bottom-right)
    description:
      'Useful things Creators choose to share — including readings, links, files, guides, recordings and other material that supports the Collective.',
    Icon: ResourcesMark,
  },
]

function PathwaysMark() {
  return (
    <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
      <path
        d="M6 26 Q 12 18 16 18 T 26 6"
        stroke="currentColor"
        strokeWidth="1.6"
        fill="none"
        strokeLinecap="round"
        opacity="0.9"
      />
      <circle cx="26" cy="6" r="2.4" fill="currentColor" />
    </svg>
  )
}

function GatheringsMark() {
  return (
    <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
      <circle cx="16" cy="18" r="4.5" fill="currentColor" opacity="0.9" />
      <path
        d="M16 12 C 13 10 13 7 16 4 C 19 7 19 10 16 12 Z"
        fill="currentColor"
        opacity="0.75"
      />
      <path
        d="M6 28 Q 16 25 26 28"
        stroke="currentColor"
        strokeWidth="1.4"
        fill="none"
        strokeLinecap="round"
        opacity="0.65"
      />
    </svg>
  )
}

function ConversationsMark() {
  return (
    <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
      <circle cx="12" cy="13" r="6.5" stroke="currentColor" strokeWidth="1.6" fill="none" opacity="0.9" />
      <circle cx="20" cy="19" r="6.5" stroke="currentColor" strokeWidth="1.6" fill="none" opacity="0.9" />
    </svg>
  )
}

function ResourcesMark() {
  return (
    <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
      <rect x="7" y="6" width="18" height="20" rx="1.5" stroke="currentColor" strokeWidth="1.6" fill="none" opacity="0.9" />
      <path
        d="M16 6 L 16 26 M 11 12 L 13.5 12 M 18.5 12 L 21 12 M 11 17 L 13.5 17 M 18.5 17 L 21 17"
        stroke="currentColor"
        strokeWidth="1.3"
        fill="none"
        opacity="0.75"
      />
    </svg>
  )
}

function StepHowItWorks({
  heroUrl, onBack, onNext,
}: {
  heroUrl: string | null
  onBack: () => void
  onNext: () => void
}) {
  return (
    <div className="text-center">
      <OnboardingHero
        imageUrl={heroUrl}
        alt=""
        fallback={<ThreeLightsScene />}
      />
      <h2
        className="mb-4 font-serif leading-tight"
        style={{ fontSize: 'clamp(1.6rem, 3.5vw, 2rem)', color: NAVY }}
      >
        How Fresh Collective works.
      </h2>
      <p
        className="mx-auto mb-10 max-w-[480px] text-[14.5px] leading-relaxed"
        style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
      >
        Fresh Collective brings together four different ways to learn,
        connect and participate. Every Collective uses them differently.
      </p>
      <div className="grid gap-4 text-left md:grid-cols-2">
        {HOW_IT_WORKS.map((item) => (
          <div
            key={item.label}
            className="relative overflow-hidden rounded-2xl p-6 md:p-7"
            style={{
              background: item.background,
              boxShadow: '0 12px 32px rgba(12, 24, 38, 0.10), 0 2px 6px rgba(12, 24, 38, 0.04)',
            }}
          >
            <div className="mb-5" style={{ color: GOLD }}>
              <item.Icon />
            </div>
            <p
              className="font-serif leading-tight"
              style={{
                fontSize: 'clamp(1.15rem, 2.2vw, 1.4rem)',
                color: '#FFFFFF',
                letterSpacing: '-0.005em',
              }}
            >
              {item.label}
            </p>
            <p
              className="mt-3 text-[13.5px] leading-[1.65]"
              style={{
                color: 'rgba(255, 255, 255, 0.80)',
                fontFamily: 'Georgia, serif',
              }}
            >
              {item.description}
            </p>
          </div>
        ))}
      </div>
      <NavRow onBack={onBack} onNext={onNext} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 4 — Arrival (natural conclusion, no repeated exposition)
// ---------------------------------------------------------------------------

function StepStartingPoint({
  heroUrl,
  onBack,
  onComplete,
  submitting,
}: {
  heroUrl: string | null
  onBack: () => void
  onComplete: () => void
  submitting: boolean
}) {
  return (
    <div className="text-center">
      <OnboardingHero
        imageUrl={heroUrl}
        alt=""
        fallback={<ArchipelagoScene />}
      />
      <h2
        className="mb-6 font-serif leading-tight"
        style={{ fontSize: 'clamp(1.75rem, 3.8vw, 2.2rem)', color: NAVY }}
      >
        You&rsquo;re ready to explore.
      </h2>
      <p
        className="mx-auto mb-5 max-w-[480px] text-[15px] leading-relaxed"
        style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
      >
        This was just a glimpse of what&rsquo;s inside. You&rsquo;ll
        discover much more simply by exploring, joining in and finding
        what feels right for you.
      </p>
      <p
        className="mx-auto mb-10 max-w-[460px] text-[14.5px] italic leading-relaxed"
        style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
      >
        Your World is waiting.
      </p>

      <NavRow
        onBack={onBack}
        onNext={onComplete}
        nextLabel={submitting ? 'Opening…' : 'Enter Your World →'}
        disabled={submitting}
      />
    </div>
  )
}
