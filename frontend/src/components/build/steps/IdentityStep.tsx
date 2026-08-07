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

export default function IdentityStep({
  value, onChange, onContinue, onBack, onSkip, heroUrl = null,
}: Props) {
  const trimmed = value.trim()
  const canContinue = trimmed.length >= 8

  return (
    <StepShell
      stepIndex={4}
      heading="In one sentence, what makes this collective unique?"
      whisper="It's the heart of the collective — what you will keep returning to."
      onBack={onBack}
      onContinue={onContinue}
      canContinue={canContinue}
      onSkip={onSkip}
      hero={
        <OnboardingHero
          imageUrl={heroUrl}
          alt=""
          fallback={<IdentityMark />}
        />
      }
    >
      <div className="mx-auto max-w-[620px]">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={3}
          maxLength={500}
          placeholder="A place for women returning to the intelligence of the body."
          className="w-full resize-none rounded-2xl px-6 py-5 text-[17px] leading-relaxed focus:outline-none"
          style={{
            background: '#FFFFFF',
            border: '1px solid rgba(12, 24, 38, 0.12)',
            boxShadow: '0 1px 3px rgba(12, 24, 38, 0.03)',
            color: '#0C1826',
            fontFamily: 'Georgia, serif',
            fontStyle: 'italic',
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
        <p
          className="mt-3 text-right text-[11px]"
          style={{ color: 'rgba(12, 24, 38, 0.42)' }}
        >
          {trimmed.length}/500
        </p>
      </div>
    </StepShell>
  )
}

function IdentityMark() {
  return (
    <svg viewBox="0 0 200 200" className="h-full w-full" aria-hidden="true">
      <circle cx="100" cy="100" r="52" fill="none" stroke="#38A09E" strokeWidth="1.2" opacity="0.40" />
      <circle cx="100" cy="100" r="28" fill="none" stroke="#38A09E" strokeWidth="1" opacity="0.55" />
      <circle cx="100" cy="100" r="6" fill="#D4B048" opacity="0.85" />
    </svg>
  )
}
