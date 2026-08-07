'use client'

import StepShell from '../StepShell'
import OnboardingHero from '@/components/onboarding/OnboardingHero'
import type { AtmosphereOption } from '@/lib/build-your-collective/types'

interface Props {
  atmospheres: AtmosphereOption[]
  value: string[]
  onChange: (keys: string[]) => void
  onContinue: () => void
  onBack: () => void
  onSkip?: () => void
  heroUrl?: string | null
}

const REQUIRED = 5

export default function AtmosphereStep({
  atmospheres, value, onChange, onContinue, onBack, onSkip, heroUrl = null,
}: Props) {
  const chosen = new Set(value)

  function toggle(key: string) {
    if (chosen.has(key)) {
      onChange(value.filter((k) => k !== key))
    } else if (chosen.size < REQUIRED) {
      onChange([...value, key])
    }
  }

  const remaining = REQUIRED - chosen.size

  return (
    <StepShell
      stepIndex={1}
      heading="How do you hope people feel when they arrive?"
      whisper={
        remaining > 0
          ? `Choose five. ${remaining} to go.`
          : 'Five chosen. Move gently to the next step.'
      }
      onBack={onBack}
      onContinue={onContinue}
      canContinue={chosen.size === REQUIRED}
      onSkip={onSkip}
      hero={
        <OnboardingHero
          imageUrl={heroUrl}
          alt=""
          fallback={<AtmosphereMark />}
        />
      }
    >
      <div className="mx-auto flex max-w-[720px] flex-wrap justify-center gap-3">
        {atmospheres.map((a) => {
          const selected = chosen.has(a.key)
          const atLimit = chosen.size >= REQUIRED && !selected
          return (
            <button
              key={a.key}
              type="button"
              onClick={() => toggle(a.key)}
              aria-pressed={selected}
              disabled={atLimit}
              className="rounded-full px-5 py-2.5 text-[13.5px] font-medium transition-all disabled:opacity-35"
              style={{
                background: selected ? 'rgba(56, 160, 158, 0.10)' : '#FFFFFF',
                border: selected
                  ? '1px solid rgba(56, 160, 158, 0.55)'
                  : '1px solid rgba(12, 24, 38, 0.14)',
                color: selected ? '#38A09E' : '#0C1826',
              }}
            >
              {a.name}
            </button>
          )
        })}
      </div>
    </StepShell>
  )
}

function AtmosphereMark() {
  return (
    <svg viewBox="0 0 200 200" className="h-full w-full" aria-hidden="true">
      <defs>
        <radialGradient id="atmosGlow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor="#D4B048" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#D4B048" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="100" cy="100" r="70" fill="url(#atmosGlow)" />
      <path d="M 20 88 Q 100 80 180 88" stroke="#38A09E" strokeWidth="1.1" fill="none" opacity="0.55" />
      <path d="M 20 112 Q 100 104 180 112" stroke="#38A09E" strokeWidth="0.9" fill="none" opacity="0.40" />
      <path d="M 20 132 Q 100 124 180 132" stroke="#38A09E" strokeWidth="0.7" fill="none" opacity="0.28" />
    </svg>
  )
}
