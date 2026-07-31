'use client'

/**
 * The quiet frame every step shares. White canvas, deep navy typography,
 * teal as the primary interaction colour, soft gold reserved for accents.
 *
 * No progress bar (Atlas Chapter 8 — no engagement loops); a horizon
 * marker orients without pressure.
 */

import { STEP_COUNT } from '@/lib/build-your-collective/types'

interface Props {
  stepIndex: number
  eyebrow?: string
  heading?: string
  whisper?: string
  onBack?: () => void
  onContinue?: () => void
  continueLabel?: string
  canContinue?: boolean
  saving?: boolean
  saveError?: string | null
  children: React.ReactNode
  /** Hides horizon marker + back button on the opening and confirmation. */
  spacious?: boolean
}

export default function StepShell({
  stepIndex, eyebrow, heading, whisper, onBack, onContinue,
  continueLabel = 'Continue', canContinue = true, saving = false,
  saveError, children, spacious = false,
}: Props) {
  return (
    <main
      className="relative min-h-screen w-full"
      style={{
        background:
          'radial-gradient(70% 40% at 50% 0%, rgba(56, 160, 158, 0.06), transparent 65%),' +
          'linear-gradient(180deg, #FFFFFF 0%, #FBFDFD 100%)',
        color: '#0C1826',
      }}
    >
      <div className="mx-auto max-w-[900px] px-6 pb-20 pt-16 md:px-10 md:pt-24">
        {(eyebrow || heading || whisper) && (
          <header className="mb-12 text-center md:mb-16">
            {eyebrow && (
              <p
                className="mb-4 text-[11px] font-semibold uppercase tracking-[0.28em]"
                style={{ color: '#38A09E' }}
              >
                {eyebrow}
              </p>
            )}
            {heading && (
              <h1
                className="font-serif text-[26px] leading-[1.2] text-navy-900 md:text-[34px]"
                style={{ color: '#0C1826' }}
              >
                {heading}
              </h1>
            )}
            {whisper && (
              <p
                className="mx-auto mt-4 max-w-[560px] text-[14.5px] italic leading-relaxed"
                style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
              >
                {whisper}
              </p>
            )}
          </header>
        )}

        <div>{children}</div>

        {(onContinue || onBack) && (
          <div className="mt-14 flex items-center justify-between gap-6">
            {onBack ? (
              <button
                type="button"
                onClick={onBack}
                className="text-[13px] font-medium transition-opacity hover:opacity-70"
                style={{ color: 'rgba(12, 24, 38, 0.55)' }}
              >
                ← Back
              </button>
            ) : <span />}
            {onContinue && (
              <button
                type="button"
                onClick={onContinue}
                disabled={!canContinue || saving}
                className="rounded-full px-7 py-3 text-[13.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-35"
                style={{
                  background: canContinue
                    ? 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)'
                    : 'rgba(12, 24, 38, 0.20)',
                  letterSpacing: '0.06em',
                }}
              >
                {saving ? 'Saving…' : continueLabel}
              </button>
            )}
          </div>
        )}

        {saveError && (
          <p className="mt-4 text-center text-[12.5px]" style={{ color: '#A64526' }}>
            {saveError}
          </p>
        )}

        {!spacious && (
          <div
            className="pointer-events-none mt-16 flex items-center justify-center gap-2"
            aria-hidden="true"
          >
            {Array.from({ length: STEP_COUNT }).map((_, i) => (
              <span
                key={i}
                className="block rounded-full transition-all duration-500"
                style={{
                  height: 2,
                  width: i === stepIndex ? 20 : 6,
                  background: i <= stepIndex ? 'rgba(56, 160, 158, 0.55)' : 'rgba(12, 24, 38, 0.12)',
                }}
              />
            ))}
          </div>
        )}
      </div>
    </main>
  )
}
