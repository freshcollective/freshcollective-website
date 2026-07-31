'use client'

import StepShell from '../StepShell'
import type { ColourPaletteOption } from '@/lib/build-your-collective/types'

interface Props {
  palettes: ColourPaletteOption[]
  value: string | null
  onChange: (key: string) => void
  onContinue: () => void
  onBack: () => void
}

/**
 * Colour Palette step (Atlas v1.2 — was "Colour Story"). The palette
 * becomes the visual identity of the collective interface — buttons,
 * accents, links, dividers. It does not affect the Location artwork.
 */
export default function ColourPaletteStep({
  palettes, value, onChange, onContinue, onBack,
}: Props) {
  return (
    <StepShell
      stepIndex={3}
      eyebrow="Three"
      heading="Which colours give your collective its voice?"
      whisper="The palette becomes the visual language of your collective — buttons, accents, links."
      onBack={onBack}
      onContinue={onContinue}
      canContinue={!!value}
    >
      <div className="grid gap-3 md:grid-cols-2">
        {palettes.map((s) => {
          const selected = value === s.key
          return (
            <button
              key={s.key}
              type="button"
              onClick={() => onChange(s.key)}
              aria-pressed={selected}
              className="group relative overflow-hidden rounded-2xl text-left transition-all"
              style={{
                background: '#FFFFFF',
                border: selected
                  ? '1px solid rgba(56, 160, 158, 0.55)'
                  : '1px solid rgba(12, 24, 38, 0.08)',
                boxShadow: selected
                  ? '0 10px 30px rgba(56, 160, 158, 0.14)'
                  : '0 1px 3px rgba(12, 24, 38, 0.04)',
                transform: selected ? 'translateY(-2px)' : 'none',
              }}
            >
              <div
                className="h-16 w-full"
                style={{
                  background: `linear-gradient(90deg, ${s.palette.background} 0%, ${s.palette.secondary} 35%, ${s.palette.primary} 70%, ${s.palette.accent} 100%)`,
                }}
              />
              <div className="flex items-center justify-between gap-3 px-5 py-3.5">
                <p className="text-[14.5px]" style={{ fontFamily: 'Georgia, serif', fontStyle: 'italic', color: '#0C1826' }}>
                  {s.name}
                </p>
                <div className="flex items-center gap-1.5" aria-hidden="true">
                  <Swatch colour={s.palette.primary} />
                  <Swatch colour={s.palette.secondary} />
                  <Swatch colour={s.palette.accent} />
                  <Swatch colour={s.palette.background} bordered />
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </StepShell>
  )
}

function Swatch({ colour, bordered = false }: { colour: string; bordered?: boolean }) {
  return (
    <span
      className="block h-3 w-3 rounded-full"
      style={{
        background: colour,
        border: bordered ? '1px solid rgba(12, 24, 38, 0.10)' : 'none',
      }}
    />
  )
}
