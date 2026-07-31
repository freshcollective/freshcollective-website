'use client'

import StepShell from '../StepShell'
import type { DraftData, Visibility, PricingType } from '@/lib/build-your-collective/types'

interface Props {
  value: DraftData
  onChange: (patch: Partial<DraftData>) => void
  onContinue: () => void
  onBack: () => void
}

export default function PracticalDetailsStep({
  value, onChange, onContinue, onBack,
}: Props) {
  const name = (value.name ?? '').trim()
  const canContinue = name.length >= 2

  const visibility: Visibility = (value.visibility ?? 'public') as Visibility
  const pricing: PricingType = (value.pricing_type ?? 'free') as PricingType

  return (
    <StepShell
      stepIndex={6}
      eyebrow="Six"
      heading="Now for the practical things."
      whisper="Simple details, quickly done."
      onBack={onBack}
      onContinue={onContinue}
      canContinue={canContinue}
    >
      <div className="mx-auto flex max-w-[560px] flex-col gap-7">
        <Field label="What is this collective called?">
          <TextInput
            value={value.name ?? ''}
            onChange={(v) => onChange({ name: v })}
            maxLength={200}
            placeholder="e.g. The Grove"
          />
        </Field>

        <Field label="One line for people passing by">
          <TextInput
            value={value.description ?? ''}
            onChange={(v) => onChange({ description: v })}
            maxLength={300}
            placeholder="e.g. A quiet place for women returning to themselves."
          />
        </Field>

        <Field label="Who can find this place?">
          <SegmentedRadio
            value={visibility}
            options={[
              { key: 'public',  label: 'Public',        hint: 'Discoverable in the universe.' },
              { key: 'link',    label: 'By invitation', hint: 'Only reachable by a link you share.' },
              { key: 'private', label: 'Private',       hint: 'For members you invite directly.' },
            ]}
            onChange={(v) => onChange({ visibility: v as Visibility })}
          />
        </Field>

        <Field label="How does someone step in?">
          <SegmentedRadio
            value={pricing}
            options={[
              { key: 'free',         label: 'Free',            hint: 'The door is open.' },
              { key: 'contribution', label: 'A contribution',  hint: 'A price, or a suggested amount.' },
            ]}
            onChange={(v) => onChange({ pricing_type: v as PricingType })}
          />
          {pricing === 'contribution' && (
            <div className="mt-4 flex flex-col gap-3">
              <TextInput
                type="number"
                value={value.pricing_amount_cents != null ? (value.pricing_amount_cents / 100).toString() : ''}
                onChange={(v) => {
                  const n = parseFloat(v)
                  onChange({ pricing_amount_cents: isNaN(n) ? null : Math.round(n * 100) })
                }}
                placeholder="Amount (in your currency)"
              />
              <TextInput
                value={value.pricing_note ?? ''}
                onChange={(v) => onChange({ pricing_note: v })}
                maxLength={300}
                placeholder="A short note, if you'd like — e.g. 'monthly, cancel any time'"
              />
            </div>
          )}
        </Field>
      </div>
    </StepShell>
  )
}

// ---------------------------------------------------------------------------

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label
        className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.20em]"
        style={{ color: '#38A09E' }}
      >
        {label}
      </label>
      {children}
    </div>
  )
}

function TextInput({
  value, onChange, placeholder, maxLength, type = 'text',
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  maxLength?: number
  type?: 'text' | 'number'
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      maxLength={maxLength}
      className="w-full rounded-xl px-4 py-3 text-[15px] focus:outline-none"
      style={{
        background: '#FFFFFF',
        border: '1px solid rgba(12, 24, 38, 0.12)',
        color: '#0C1826',
      }}
      onFocus={(e) => {
        e.currentTarget.style.border = '1px solid rgba(56, 160, 158, 0.55)'
        e.currentTarget.style.boxShadow = '0 0 0 4px rgba(56, 160, 158, 0.10)'
      }}
      onBlur={(e) => {
        e.currentTarget.style.border = '1px solid rgba(12, 24, 38, 0.12)'
        e.currentTarget.style.boxShadow = 'none'
      }}
    />
  )
}

function SegmentedRadio<T extends string>({
  value, options, onChange,
}: {
  value: T
  options: { key: T; label: string; hint: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div className="flex flex-col gap-2">
      {options.map((opt) => {
        const selected = value === opt.key
        return (
          <button
            key={opt.key}
            type="button"
            onClick={() => onChange(opt.key)}
            className="flex items-start gap-3 rounded-xl px-4 py-3 text-left transition-colors"
            style={{
              background: selected ? 'rgba(56, 160, 158, 0.06)' : '#FFFFFF',
              border: selected
                ? '1px solid rgba(56, 160, 158, 0.55)'
                : '1px solid rgba(12, 24, 38, 0.10)',
            }}
          >
            <span
              className="mt-1 block h-3.5 w-3.5 shrink-0 rounded-full"
              style={{
                background: selected ? '#38A09E' : 'transparent',
                border: selected ? '1px solid #38A09E' : '1px solid rgba(12, 24, 38, 0.30)',
              }}
              aria-hidden="true"
            />
            <span className="flex flex-col gap-0.5">
              <span className="text-[14px] font-semibold" style={{ color: '#0C1826' }}>
                {opt.label}
              </span>
              <span className="text-[12.5px]" style={{ color: 'rgba(12, 24, 38, 0.60)' }}>
                {opt.hint}
              </span>
            </span>
          </button>
        )
      })}
    </div>
  )
}
