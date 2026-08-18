/**
 * FIP4B1 — pure copy composer for the plan-recovery banner.
 *
 * Extracted from the React component so it can be unit-tested with
 * Node's built-in test runner without importing JSX. The React
 * component is a thin wrapper that renders the strings this
 * function produces.
 */

import type { MemberPlanState } from '@/types/platform'

export interface PlanRecoveryCopy {
  headline: string
  body: string
  progress: string
}

function formatGraceDate(
  iso: string | null, timezone: string | null | undefined,
): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  try {
    return d.toLocaleDateString('en-AU', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      timeZone: timezone || undefined,
    })
  } catch {
    return d.toLocaleDateString('en-AU', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    })
  }
}

export function planRecoveryCopy(
  state: MemberPlanState, timezone: string | null | undefined,
): PlanRecoveryCopy {
  const planName = state.payment_option_name ?? 'your payment plan'
  const progress = `${state.installments_paid} of ${state.installments_expected} paid`
  const isSuspended = state.status === 'suspended'
  if (isSuspended) {
    return {
      headline: 'Your payment plan needs attention',
      body: `Your access to ${planName} is paused because we couldn\u2019t process your latest payment. Update your payment details to restore access.`,
      progress,
    }
  }
  const graceDate = formatGraceDate(state.grace_expires_at, timezone)
  const body = graceDate
    ? `We couldn\u2019t process your latest payment for ${planName}. Your access is still active until ${graceDate}. Please update your payment details before then to keep your access active.`
    : `We couldn\u2019t process your latest payment for ${planName}. You still have access for now — please update your payment details to keep it active.`
  return {
    headline: 'Your payment needs attention',
    body,
    progress,
  }
}
