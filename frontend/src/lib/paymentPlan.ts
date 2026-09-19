/**
 * FIP4A — shared display helpers for PaymentOption schedules.
 *
 * Every member surface that renders a purchase choice
 * (`ScheduleChoice` on the Series sidebar, `PaymentOptionSelector`
 * on the Pathway checkout page, the pre-checkout summary) must
 * use the same language, so a member sees "3 weekly payments of
 * A$20" the same way everywhere.
 *
 * Provider terminology (Stripe, SubscriptionSchedule, invoice)
 * stays internal — nothing in this module should reference it.
 * Product language only:
 *
 *   * "Pay in full"                        — single-transaction schedules
 *   * "Payment plan"                       — finite instalment schedules
 *   * "weekly" / "fortnightly" / "monthly" — humanised cadence
 *   * "N weekly payments of A$X"           — instalment description
 *   * "A$Y total"                          — total commitment line
 */

import type {
  PaymentOptionScheduleSummary,
  PublicPaymentOptionSchedule,
} from '@/types/platform'

/** Union of the two shapes served today. Both carry the fields
 *  these helpers touch. */
export type AnyPaymentSchedule =
  | Pick<
      PaymentOptionScheduleSummary,
      | 'schedule_type'
      | 'total_amount_cents'
      | 'installment_amount_cents'
      | 'installment_count'
      | 'interval'
      | 'currency'
      | 'name'
    >
  | Pick<
      PublicPaymentOptionSchedule,
      | 'schedule_type'
      | 'total_amount_cents'
      | 'installment_amount_cents'
      | 'installment_count'
      | 'interval'
      | 'currency'
      | 'name'
    >

/** Format cents as a currency string. AUD/USD render with `$`;
 *  everything else prefixes the ISO code so unknown currencies
 *  never look like they're being silently displayed as dollars. */
export function formatMoney(cents: number, currency: string): string {
  const symbol =
    currency === 'AUD' || currency === 'USD' ? '$' : `${currency} `
  const dollars = cents / 100
  return `${symbol}${Number.isInteger(dollars) ? dollars : dollars.toFixed(2)}`
}

/** Humanise cadence — the frontend never surfaces `week` /
 *  `fortnight` / `month` verbatim. */
export function humanCadence(interval: string | null): string | null {
  if (!interval) return null
  switch (interval) {
    case 'week':
      return 'weekly'
    case 'fortnight':
      return 'fortnightly'
    case 'month':
      return 'monthly'
    default:
      return interval
  }
}

/** Adjective form — "3 **weekly** payments of A$20". Falls back
 *  to "recurring" when the cadence is missing. */
export function cadenceAdjective(interval: string | null): string {
  return humanCadence(interval) ?? 'recurring'
}

/** Label for the choice header — "Pay in full" / "Payment plan". */
export function scheduleKindLabel(
  schedule: Pick<AnyPaymentSchedule, 'schedule_type' | 'name'>,
): string {
  if (schedule.schedule_type === 'recurring_installments') return 'Payment plan'
  if (schedule.schedule_type === 'pay_in_full') return 'Pay in full'
  // Fall back to the creator-authored name for exotic types
  // (currently only 'manual', which never renders member-checkoutable).
  return schedule.name || 'Payment option'
}

/** Short one-line description — used in the choice header row.
 *
 *   "3 weekly payments of A$20"
 *   "A$600 once"
 */
export function scheduleShortDescription(
  schedule: AnyPaymentSchedule,
): string {
  if (schedule.schedule_type === 'recurring_installments') {
    const per =
      schedule.installment_amount_cents != null
        ? formatMoney(schedule.installment_amount_cents, schedule.currency)
        : '—'
    const cadence = cadenceAdjective(schedule.interval)
    const count = schedule.installment_count
    if (count && count > 0) {
      return `${count} ${cadence} payments of ${per}`
    }
    return `${per} ${cadence}`
  }
  if (
    schedule.schedule_type === 'pay_in_full' &&
    schedule.total_amount_cents != null
  ) {
    return `${formatMoney(
      schedule.total_amount_cents,
      schedule.currency,
    )} once`
  }
  return schedule.name || ''
}

/** Total-commitment line — always printed alongside a payment
 *  plan so the member never has to do the multiplication in
 *  their head. Returns null for pay-in-full (the short
 *  description already contains the number). */
export function scheduleTotalLine(schedule: AnyPaymentSchedule): string | null {
  if (schedule.schedule_type !== 'recurring_installments') return null
  if (schedule.total_amount_cents != null) {
    return `${formatMoney(schedule.total_amount_cents, schedule.currency)} total`
  }
  if (
    schedule.installment_amount_cents != null &&
    schedule.installment_count != null &&
    schedule.installment_count > 0
  ) {
    return `${formatMoney(
      schedule.installment_amount_cents * schedule.installment_count,
      schedule.currency,
    )} total`
  }
  return null
}

/** Full pre-Stripe disclosure paragraph.
 *
 *   "3 weekly payments of A$20. A$60 total. Your card will be
 *    charged automatically according to this schedule. Access
 *    begins after your first payment succeeds."
 *
 * Pay-in-full returns a shorter sentence — no automatic-charge
 * language because there's only one charge, and it happens
 * inside Checkout. */
export function scheduleDisclosureCopy(schedule: AnyPaymentSchedule): string {
  if (schedule.schedule_type === 'recurring_installments') {
    const parts = [scheduleShortDescription(schedule)]
    const totalLine = scheduleTotalLine(schedule)
    if (totalLine) parts.push(totalLine)
    parts.push(
      'Your card will be charged automatically according to this schedule.',
    )
    parts.push('Access begins after your first payment succeeds.')
    return parts.join(' ')
  }
  if (
    schedule.schedule_type === 'pay_in_full' &&
    schedule.total_amount_cents != null
  ) {
    return `${formatMoney(
      schedule.total_amount_cents,
      schedule.currency,
    )} paid now. Access begins immediately.`
  }
  return schedule.name || ''
}

/** CTA button label. Kept short. */
export function scheduleCtaLabel(schedule: AnyPaymentSchedule): string {
  if (schedule.schedule_type === 'recurring_installments') {
    return 'Start payment plan'
  }
  if (
    schedule.schedule_type === 'pay_in_full' &&
    schedule.total_amount_cents != null
  ) {
    return `Pay ${formatMoney(
      schedule.total_amount_cents,
      schedule.currency,
    )}`
  }
  return 'Continue to checkout'
}


/** Structured copy for the pre-Stripe confirmation step.
 *
 * Stripe's setup-mode page cannot show an amount — it has no line
 * items, so it renders a bare card form with a "Save" button. That
 * makes Fresh Collective's own screen the last place a member sees
 * the commitment stated plainly before they hand over a card, so
 * these strings carry real weight.
 *
 * Returns ``null`` for anything that is not a finite payment plan
 * with the figures needed to state the commitment honestly — the
 * caller then skips the confirmation step rather than showing a
 * half-filled one. */
export interface PlanConfirmationCopy {
  /** e.g. "A$37.80 charged after setup" */
  firstCharge: string
  /** e.g. "Then 9 weekly payments of A$37.80" */
  thenLine: string
  /** e.g. "A$378 total" */
  totalLine: string
  /** The per-payment amount on its own, for emphasis. */
  amount: string
  /** Number of payments in the whole plan. */
  count: number
}

export function planConfirmationCopy(
  schedule: AnyPaymentSchedule,
): PlanConfirmationCopy | null {
  if (schedule.schedule_type !== 'recurring_installments') return null

  const amountCents = schedule.installment_amount_cents
  const count = schedule.installment_count
  if (amountCents == null || count == null || count < 1) return null

  const amount = formatMoney(amountCents, schedule.currency)
  const cadence = cadenceAdjective(schedule.interval)
  const remaining = count - 1

  // The total the schedule was saved with, when present; otherwise
  // derived. Never shown as a guess — if neither is available the
  // line is the per-payment figure alone.
  const totalCents = schedule.total_amount_cents ?? amountCents * count
  const totalLine = `${formatMoney(totalCents, schedule.currency)} total`

  const thenLine =
    remaining === 0
      ? 'This is the only payment.'
      : remaining === 1
        ? `Then 1 ${cadence} payment of ${amount}`
        : `Then ${remaining} ${cadence} payments of ${amount}`

  return {
    firstCharge: `${amount} charged after setup`,
    thenLine,
    totalLine,
    amount,
    count,
  }
}
