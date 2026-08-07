'use client'

import StepShell from '../StepShell'
import OnboardingHero from '@/components/onboarding/OnboardingHero'

interface Props {
  value: string
  onChange: (v: string) => void
  onContinue: () => void
  onBack: () => void
  onSkip?: () => void
  heroUrl?: string | null
}

export default function WelcomeMessageStep({
  value, onChange, onContinue, onBack, onSkip, heroUrl = null,
}: Props) {
  const trimmed = value.trim()
  const canContinue = trimmed.length >= 20
  const whisper =
    trimmed.length === 0
      ? 'If you\u2019d like, write a few words to welcome people into your collective.'
      : 'Speak to them the way you would if they had just walked through your door.'

  return (
    <StepShell
      stepIndex={5}
      heading="How would you like to welcome people?"
      whisper={whisper}
      onBack={onBack}
      onContinue={onContinue}
      canContinue={canContinue}
      onSkip={onSkip}
      hero={
        <OnboardingHero
          imageUrl={heroUrl}
          alt=""
          fallback={<WelcomeMessageMark />}
        />
      }
    >
      <div className="mx-auto max-w-[620px]">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={7}
          placeholder="You are welcome here. Take your time. There is no rush."
          className="w-full resize-none rounded-2xl px-6 py-6 text-[17px] leading-[1.7] focus:outline-none"
          style={{
            background: '#FFFFFF',
            border: '1px solid rgba(12, 24, 38, 0.12)',
            boxShadow: '0 1px 3px rgba(12, 24, 38, 0.03)',
            color: '#0C1826',
            fontFamily: 'Georgia, serif',
          }}
          onFocus={(e) => {
            e.currentTarget.style.border = '1px solid rgba(56, 160, 158, 0.55)'
            e.currentTarget.style.boxShadow = '0 0 0 4px rgba(56, 160, 158, 0.10)'
          }}
          onBlur={(e) => {
            e.currentTarget.style.border = '1px solid rgba(12, 24, 38, 0.12)'
            e.currentTarget.style.boxShadow = '0 1px 3px rgba(12, 24, 38, 0.03)'
          }}
        />
      </div>
    </StepShell>
  )
}

function WelcomeMessageMark() {
  return (
    <svg viewBox="0 0 200 200" className="h-full w-full" aria-hidden="true">
      <rect x="66" y="70" width="68" height="88" rx="4" fill="none" stroke="#38A09E" strokeWidth="1.2" opacity="0.55" />
      <path d="M 100 158 L 100 70" stroke="#38A09E" strokeWidth="1" opacity="0.45" />
      <path d="M 100 70 L 100 60 L 122 78" stroke="#D4B048" strokeWidth="1.3" fill="none" opacity="0.75" />
      <circle cx="118" cy="114" r="2.5" fill="#D4B048" opacity="0.85" />
    </svg>
  )
}
