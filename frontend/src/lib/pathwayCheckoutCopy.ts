/**
 * Copy for the Pathway checkout page's left-hand cards.
 *
 * Pure, so the wording is unit-testable under Node's test runner
 * without importing JSX — and so the strings live somewhere a test can
 * assert what they must never contain again.
 *
 * Why this file exists
 * --------------------
 * The ``payment_options`` branch of the checkout page was written while
 * EMBODY was the only Pathway using it, and the branch hard-coded
 * EMBODY's own particulars: a ten-week term, Monday/Thursday/Saturday,
 * South Croydon. Those are not facts about payment options — they are
 * facts about one collective's offering — and every other Pathway that
 * reached payment-options mode rendered them as its own.
 *
 * None of it had any backing field on the payload. The real versions of
 * those facts live on the creator's configured Payment Options
 * (``name``, ``description``, ``buyer_note``, the schedules) and are
 * already rendered, from real data, by ``PaymentOptionSelector`` on the
 * same page. The fix is not to re-derive them here but to stop
 * inventing them: this module says only what the payload can support,
 * and the Options speak for themselves.
 *
 * EMBODY keeps working for exactly that reason — its term, days and
 * venue are authored into its Payment Options, not into this file.
 */

import type { PaymentOptionSummary } from '@/types/platform'

export interface PaymentCardCopy {
  title: string
  blurb: string
}

/**
 * The "Payment" card — what kind of payment this Pathway asks for.
 *
 * In payment-options mode it is a pointer to the selector below, not a
 * second description of the offer. Mentioning instalments only when a
 * schedule actually offers them keeps it honest both ways: the old copy
 * asserted "Pay in full to lock in your term" on a Pathway that might
 * have a payment plan.
 */
export function paymentCardCopy(
  pricingMode: string | null | undefined,
  options: PaymentOptionSummary[] | null | undefined,
): PaymentCardCopy {
  if (pricingMode !== 'payment_options') {
    return {
      title: 'Pay in full',
      blurb: 'One payment to unlock this pathway.',
    }
  }

  const list = options ?? []
  if (list.length === 0) {
    // Same wording as PaymentOptionSelector's own empty state, so the
    // two halves of the page do not disagree about what is going on.
    return {
      title: 'Payment options',
      blurb: 'Ways to join are coming soon.',
    }
  }

  const hasInstalments = list.some((opt) =>
    (opt.schedules ?? []).some(
      (s) => (s.installment_count ?? 0) > 1
        || s.schedule_type === 'recurring_installments',
    ),
  )

  return {
    title: 'Payment options',
    blurb: hasInstalments
      ? 'Choose the option that suits you. Some can be paid in instalments.'
      : 'Choose the option that suits you.',
  }
}

/**
 * The "What's included" list.
 *
 * Pathway-level facts only, and the same list in both pricing modes.
 * What a given Payment Option includes differs per option — that is the
 * whole point of having several — so it belongs on the option's own
 * card, where ``PaymentOptionSelector`` already renders the creator's
 * ``description`` and ``buyer_note``. A single shared list cannot be
 * true of every option at once, which is how the EMBODY copy came to be
 * shown to Pathways it was never about.
 */
export function includedLines(
  pathway: { step_count?: number | null } | null | undefined,
): string[] {
  const steps = pathway?.step_count ?? 0
  return [
    // The old string interpolated an empty count at zero and rendered
    // "Access to all  pathway steps", double space and all.
    steps > 0
      ? `Access to all ${steps} pathway steps`
      : 'Access to every step in this pathway',
    'Progress tracking',
    'Resources attached to steps',
  ]
}
