import type { CreatorPlanOut, CreatorSubscriptionOut } from '@/types/platform'

/**
 * What the "Your creator plan" card should say.
 *
 * The card used to say it without asking: "Founding Creator Access",
 * "14 days free", "then $19 / month" were literal strings, so every
 * creator read the same terms regardless of the plan they were on.
 * A Founding Creator on $0 was quoted $19 and a trial they were not
 * in; a Pro creator paying $79 was quoted $19 as well.
 *
 * Everything here derives from ``billing.current_plan`` — the
 * ``creator_plans`` row World Management edits — and
 * ``billing.subscription``, which is the only thing that knows
 * whether a trial or a cancellation is real.
 *
 * On cancellation, carefully. ``cancel_at_period_end`` leaves the
 * subscription ``active`` until Stripe closes the period; the model
 * says so explicitly — *"Creator retains commercial capability
 * through the paid-through date."* So a scheduled cancellation is an
 * active plan with an end date, and ``status='cancelled'`` means the
 * period has already closed. Saying "cancelled" of the first would
 * tell a paying creator their access had gone while it had not.
 */

export interface CreatorPlanCardView {
  /** The plan's real name, or null when there is no plan to describe. */
  planName: string | null
  /** "$0 / month", "$19 / month", "Talk to us", or null. */
  priceLabel: string | null
  /** "0%" / "8%", or null when no fee is known. */
  feeLabel: string | null
  /** Trial line — present only while genuinely trialing. */
  trialLabel: string | null
  /** A factual line about the subscription's state, when there is one
   *  worth saying. Never speculative. */
  statusNote: string | null
  /** True when there is no plan at all, so the card shows a neutral
   *  state instead of inventing terms. */
  isUnknown: boolean
}

function formatMoney(cents: number, currency: string): string {
  const amount = cents / 100
  const symbol = currency === 'AUD' || currency === 'USD' ? '$' : `${currency} `
  return `${symbol}${Number.isInteger(amount) ? amount : amount.toFixed(2)}`
}

function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export function buildCreatorPlanCard(
  plan: CreatorPlanOut | null | undefined,
  subscription: CreatorSubscriptionOut | null | undefined,
  feeBasisPoints: number | null | undefined,
): CreatorPlanCardView {
  const feeLabel = feeBasisPoints == null
    ? null
    : `${(feeBasisPoints / 100).toFixed(feeBasisPoints % 100 === 0 ? 0 : 1)}%`

  if (!plan) {
    // A platform owner with no creator subscription lands here, as
    // does a creator whose plan could not be resolved. Neither is a
    // reason to quote someone a price.
    return {
      planName: null, priceLabel: null, feeLabel,
      trialLabel: null, statusNote: null, isUnknown: true,
    }
  }

  // Null price is the Organisation plan — "Talk to us", not free.
  const priceLabel = plan.monthly_price_cents == null
    ? 'Talk to us'
    : `${formatMoney(plan.monthly_price_cents, plan.currency)} / month`

  const status = subscription?.status
  const endsOn = formatDate(
    subscription?.current_period_end ?? subscription?.ends_at,
  )

  // Only a trialing subscription gets a trial line, and only with the
  // date the system actually holds.
  const trialLabel = status === 'trialing'
    ? (endsOn ? `Free trial until ${endsOn}` : 'Free trial')
    : null

  let statusNote: string | null = null
  if (status === 'trialing') {
    statusNote = endsOn ? `Billing starts ${endsOn}.` : null
  } else if (status === 'active' && subscription?.cancel_at_period_end) {
    // Still active. The plan runs to the paid-through date.
    statusNote = endsOn
      ? `Cancels on ${endsOn}. Your plan continues until then.`
      : 'Cancellation scheduled. Your plan continues until the end of the current period.'
  } else if (status === 'past_due') {
    const graceEnds = formatDate(subscription?.grace_expires_at)
    statusNote = graceEnds
      ? `Payment overdue. Your plan continues until ${graceEnds}.`
      : 'Payment overdue.'
  } else if (status === 'cancelled') {
    // Reached only once the period has closed.
    statusNote = endsOn ? `Ended on ${endsOn}.` : 'This plan has ended.'
  } else if (status === 'unpaid') {
    statusNote = 'This plan is inactive because payment was not completed.'
  }

  return {
    planName: plan.name,
    priceLabel,
    feeLabel,
    trialLabel,
    statusNote,
    isUnknown: false,
  }
}
