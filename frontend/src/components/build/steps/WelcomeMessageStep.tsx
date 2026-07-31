'use client'

import StepShell from '../StepShell'

interface Props {
  value: string
  onChange: (v: string) => void
  onContinue: () => void
  onBack: () => void
}

export default function WelcomeMessageStep({
  value, onChange, onContinue, onBack,
}: Props) {
  const trimmed = value.trim()
  const canContinue = trimmed.length >= 20
  const whisper =
    trimmed.length > 0 && trimmed.length < 30
      ? 'A little more, if you wish.'
      : 'Speak to them the way you would if they had just walked through your door.'

  return (
    <StepShell
      stepIndex={5}
      eyebrow="Five"
      heading="How would you like to welcome people?"
      whisper={whisper}
      onBack={onBack}
      onContinue={onContinue}
      canContinue={canContinue}
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
