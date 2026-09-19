'use client'

/** Small shared pieces for the Email Templates surface. */

import { classificationLabel, deliveryLabel, stateLabel } from '@/lib/emailTemplates'
import type { Classification } from '@/lib/emailTemplates'
import {
  CORAL, GOLD, HAIRLINE, INK, INK_MUTED, NAVY, NEUTRAL, TEAL,
} from './tokens'
import type { Hue } from './tokens'

export function Pill({
  hue, children, title,
}: {
  hue: Hue
  children: React.ReactNode
  title?: string
}) {
  return (
    <span
      title={title}
      className="inline-flex items-center rounded-full px-2 py-[3px] text-[11px] font-medium whitespace-nowrap"
      style={{ background: hue.bg, border: `1px solid ${hue.border}`, color: hue.text }}
    >
      {children}
    </span>
  )
}

const CLASSIFICATION_HUE: Record<Classification, Hue> = {
  editable: TEAL,
  partial: NAVY,
  system: NEUTRAL,
}

export function ClassificationPill({ value }: { value: Classification }) {
  return (
    <Pill hue={CLASSIFICATION_HUE[value]}>{classificationLabel(value)}</Pill>
  )
}

export function DeliveryPill({ transactional }: { transactional: boolean }) {
  return (
    <Pill
      hue={transactional ? NAVY : NEUTRAL}
      title={
        transactional
          ? 'Always delivered — a member cannot switch this one off.'
          : 'A member can turn this off in their Stay Connected preferences.'
      }
    >
      {deliveryLabel(transactional)}
    </Pill>
  )
}

export function StatePill({ customised }: { customised: boolean }) {
  return (
    <Pill hue={customised ? TEAL : NEUTRAL}>{stateLabel(customised)}</Pill>
  )
}

export function StalePill({ label = 'Default has changed' }: { label?: string }) {
  return <Pill hue={GOLD}>⚠ {label}</Pill>
}

export function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[12px] leading-relaxed" style={{ color: CORAL.text }}>
      {children}
    </p>
  )
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="text-[15px] font-semibold"
      style={{ color: INK, letterSpacing: '-0.01em' }}
    >
      {children}
    </h2>
  )
}

export function Divider() {
  return <div style={{ borderTop: HAIRLINE }} />
}

export function Muted({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[13px] leading-relaxed" style={{ color: INK_MUTED }}>
      {children}
    </p>
  )
}

export function PrimaryButton({
  onClick, disabled, children, type = 'button',
}: {
  onClick?: () => void
  disabled?: boolean
  children: React.ReactNode
  type?: 'button' | 'submit'
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="rounded-lg px-4 py-2 text-[13px] font-semibold text-white transition-colors disabled:cursor-not-allowed"
      style={{ background: disabled ? 'rgba(12,24,38,0.18)' : '#22a598' }}
    >
      {children}
    </button>
  )
}

export function QuietButton({
  onClick, disabled, children, tone = 'neutral',
}: {
  onClick?: () => void
  disabled?: boolean
  children: React.ReactNode
  tone?: 'neutral' | 'danger'
}) {
  const color = tone === 'danger' ? CORAL.text : INK_MUTED
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors hover:bg-[rgba(12,24,38,0.04)] disabled:opacity-40 disabled:cursor-not-allowed"
      style={{ color, border: '1px solid rgba(12, 24, 38, 0.12)' }}
    >
      {children}
    </button>
  )
}
