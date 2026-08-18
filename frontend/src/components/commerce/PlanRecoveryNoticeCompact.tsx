/**
 * FIP4B2 — compact plan-recovery notice for the Pathway content shell.
 *
 * A member who clicks Begin/Continue bypasses the About page and
 * lands directly on the step reader. Without a visible reminder they
 * can miss the payment_problem banner entirely, then be surprised
 * when the plan lapses to suspended.
 *
 * This is the SHORT companion to `<PlanRecoveryBanner>`. Same data
 * (`MemberPlanState`), same CTA client (`<RepairPaymentCta>`), same
 * amber/terracotta palette — one line of copy instead of a
 * paragraph, no progress counter (the sidebar already shows it), no
 * dedicated body text. Placed inline above the step content so it
 * reads as a single strip, not a full-width alert.
 *
 * In practice only the `payment_problem` state reaches the step
 * reader (a suspended member has entitlement=suspended and is
 * blocked upstream). The `suspended` branch is kept for defence in
 * depth — if a routing/edge case ever lets a suspended member reach
 * step content, the notice tells them why.
 */

import type { MemberPlanState } from '@/types/platform'
import { RepairPaymentCta } from './RepairPaymentCta'

interface Props {
  state: MemberPlanState
  /** Space timezone — mirrors the About-page banner so the grace
   *  deadline reads in the Collective's local frame. */
  timezone?: string | null
}

function formatGraceDate(
  iso: string | null | undefined, tz: string | null | undefined,
): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  try {
    return d.toLocaleDateString('en-AU', {
      day: 'numeric', month: 'long', year: 'numeric',
      timeZone: tz || undefined,
    })
  } catch {
    return d.toLocaleDateString('en-AU', {
      day: 'numeric', month: 'long', year: 'numeric',
    })
  }
}

export function PlanRecoveryNoticeCompact({ state, timezone }: Props) {
  const isSuspended = state.status === 'suspended'

  const palette = isSuspended
    ? { bg: 'rgba(180, 83, 9, 0.06)', border: 'rgba(180, 83, 9, 0.24)', accent: '#B45309' }
    : { bg: 'rgba(212, 176, 72, 0.10)', border: 'rgba(212, 176, 72, 0.30)', accent: '#8A6A15' }

  const graceDate = formatGraceDate(state.grace_expires_at, timezone)
  const message = isSuspended
    ? 'Payment needs attention — access is paused'
    : graceDate
      ? `Payment needs attention — access active until ${graceDate}`
      : 'Payment needs attention'

  return (
    <div
      className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-2.5"
      style={{
        background: palette.bg,
        border: `1px solid ${palette.border}`,
      }}
      role="status"
    >
      <p
        className="text-[12.5px] font-medium leading-snug"
        style={{ color: palette.accent }}
      >
        {message}
      </p>
      <RepairPaymentCta planId={state.id} accent={palette.accent} compact />
    </div>
  )
}
