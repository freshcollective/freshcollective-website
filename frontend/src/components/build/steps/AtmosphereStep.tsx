'use client'

import StepShell from '../StepShell'
import type { AtmosphereOption } from '@/lib/build-your-collective/types'

interface Props {
  atmospheres: AtmosphereOption[]
  value: string[]
  onChange: (keys: string[]) => void
  onContinue: () => void
  onBack: () => void
}

const REQUIRED = 5

export default function AtmosphereStep({
  atmospheres, value, onChange, onContinue, onBack,
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
      stepIndex={2}
      eyebrow="Two"
      heading="How do you hope people feel when they arrive?"
      whisper={
        remaining > 0
          ? `Choose five. ${remaining} to go.`
          : 'Five chosen. Move gently to the next step.'
      }
      onBack={onBack}
      onContinue={onContinue}
      canContinue={chosen.size === REQUIRED}
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
