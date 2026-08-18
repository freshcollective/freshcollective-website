/**
 * FIP4B1 — member payment-plan recovery banner.
 * FIP4B2 — real "Update payment details" CTA wired through to the
 * shared repair endpoint.
 *
 * Renders TWO calm, non-alarming states:
 *
 *   ``payment_problem`` — the member's card failed on their most
 *   recent instalment but access remains active during the 7-day
 *   grace window. Shows the grace deadline formatted in the
 *   Collective timezone and prompts the member to update payment
 *   details "before <date>".
 *
 *   ``suspended`` — grace expired without recovery, access is
 *   paused. Shows a firmer but still non-punitive recovery message
 *   and directs the member to update payment details.
 *
 * The interactive CTA is delegated to `RepairPaymentCta` (client
 * component) so this banner stays server-rendered — palette
 * derivation, copy composition, and layout all happen at request
 * time. Only the button + POST + redirect needs a client boundary.
 *
 * Copy is intentionally warm and calm — no red banners, no scary
 * language. This is a member who almost certainly wants to fix
 * their card and continue.
 */

import type { MemberPlanState } from '@/types/platform'
import { planRecoveryCopy } from '@/lib/planRecoveryCopy'
import { RepairPaymentCta } from './RepairPaymentCta'

interface Props {
  state: MemberPlanState
  /** Space timezone (from ``SpaceResponse.timezone``). Used to
   *  format ``grace_expires_at`` so the date matches the
   *  Collective's local frame. Falls back to browser locale if
   *  unset. */
  timezone?: string | null
}

export function PlanRecoveryBanner({ state, timezone }: Props) {
  const isSuspended = state.status === 'suspended'
  const copy = planRecoveryCopy(state, timezone)

  // Palette — soft amber for grace, warmer terracotta for suspended.
  // Neither is red; both stay inside the Fresh Collective feel.
  const palette = isSuspended
    ? { bg: 'rgba(180, 83, 9, 0.06)', border: 'rgba(180, 83, 9, 0.24)', accent: '#B45309' }
    : { bg: 'rgba(212, 176, 72, 0.10)', border: 'rgba(212, 176, 72, 0.30)', accent: '#8A6A15' }

  return (
    <div
      className="rounded-2xl px-5 py-4"
      style={{
        background: palette.bg,
        border: `1px solid ${palette.border}`,
      }}
      role="status"
    >
      <p
        className="mb-1 text-[13px] font-semibold"
        style={{ color: palette.accent }}
      >
        {copy.headline}
      </p>
      <p className="text-[13px] leading-relaxed text-navy-900">
        {copy.body}
      </p>
      <p className="mt-1 text-[11px] text-slate-500">
        {copy.progress}
      </p>
      <RepairPaymentCta planId={state.id} accent={palette.accent} />
    </div>
  )
}
