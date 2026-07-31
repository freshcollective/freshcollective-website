'use client'

import StepShell from '../StepShell'

interface Props {
  onBegin: () => void
}

export default function WelcomeStep({ onBegin }: Props) {
  return (
    <StepShell
      stepIndex={0}
      spacious
      onContinue={onBegin}
      continueLabel="Begin"
    >
      <div className="mx-auto max-w-[640px] pt-6 text-center">
        <p
          className="mb-5 text-[11px] font-semibold uppercase tracking-[0.32em]"
          style={{ color: '#38A09E' }}
        >
          Build Your Place
        </p>
        <h1
          className="font-serif text-[30px] leading-[1.25] md:text-[40px]"
          style={{ color: '#0C1826' }}
        >
          Every collective begins with a place.
        </h1>
        <p
          className="mx-auto mt-8 max-w-[520px] text-[16px] leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.72)', fontFamily: 'Georgia, serif' }}
        >
          Before we build your collective, let&apos;s create the kind of place you&apos;re inviting people into.
        </p>
      </div>
    </StepShell>
  )
}
